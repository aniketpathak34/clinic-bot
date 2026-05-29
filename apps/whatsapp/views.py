import json
import logging
from django.conf import settings
from django.http import HttpResponse, HttpRequest
from ninja import Router

from apps.clinic.models import Clinic
from apps.conversations.engine import handle_message
from apps.conversations.response import BotResponse
from apps.observability import log
from apps.observability.context import new_trace, set_correlation

from .utils import extract_message_from_webhook, get_whatsapp_service

logger = logging.getLogger(__name__)

router = Router()


@router.get("/whatsapp/")
def whatsapp_webhook_verify(request: HttpRequest):
    """Meta WhatsApp Cloud API webhook verification."""
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if mode == 'subscribe' and token == settings.WHATSAPP_VERIFY_TOKEN:
        log.event('webhook_verified', message='Meta webhook subscription handshake OK')
        return HttpResponse(challenge, content_type='text/plain')
    log.warn('webhook_verify_failed',
             message='Bad verify token or mode',
             mode=mode, has_token=bool(token))
    return HttpResponse('Forbidden', status=403)


@router.post("/whatsapp/")
def whatsapp_webhook_receive(request: HttpRequest):
    """Receive incoming WhatsApp messages from Meta."""
    # Fresh trace — every inbound webhook gets its own ID, threaded through
    # every downstream log call automatically via contextvars.
    new_trace()

    with log.span('webhook') as webhook_span:
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError as e:
            log.warn('webhook_invalid_json', exc=e,
                     message='Body was not valid JSON')
            return {"status": "invalid_json"}

        phone, text, display_number = extract_message_from_webhook(payload)

        if not phone or not text:
            # Status callback, read receipt, or empty — ack and move on.
            log.event('webhook_non_message',
                      message='Webhook had no user message (likely status callback)',
                      had_phone=bool(phone), had_text=bool(text),
                      display_number=display_number)
            return {"status": "no_message"}

        # Set correlation context BEFORE clinic lookup so we know who texted
        # even if the clinic lookup fails.
        set_correlation(whatsapp_number=phone)

        clinic = Clinic.find_by_display_number(display_number) if display_number else None
        if not clinic:
            log.warn('webhook_unmatched_clinic',
                     message='No Clinic registered for this display_phone_number',
                     display_number=display_number, sender_digit10=phone[-10:])
            return {"status": "unknown_clinic"}

        set_correlation(clinic_id=clinic.id)
        webhook_span.data.update({
            'clinic_code': clinic.clinic_code,
            'sender_digit10': phone[-10:],
            'text_preview': text[:60],
        })
        log.event('webhook_received',
                  message=f'Inbound from …{phone[-4:]} to {clinic.clinic_code}',
                  clinic_code=clinic.clinic_code,
                  sender_digit10=phone[-10:],
                  text_preview=text[:60])

        try:
            response = handle_message(phone, text, clinic=clinic)
            with log.span('send_response',
                          clinic_code=clinic.clinic_code,
                          recipient_digit10=phone[-10:]):
                send_bot_response(phone, response, clinic=clinic)
        except Exception as e:
            log.error('webhook_handler_crashed', exc=e,
                      message='Engine or send_bot_response raised — bot did NOT reply')
            # Return 200 anyway so Meta doesn't retry
            return {"status": "error"}

        return {"status": "ok"}


def send_bot_response(phone: str, response, clinic=None):
    """Send the appropriate message type based on BotResponse.

    Tries interactive (buttons/list) first, falls back to plain text.
    """
    service = get_whatsapp_service(clinic=clinic)

    if isinstance(response, str):
        service.send_message(phone, response)
        return

    if not isinstance(response, BotResponse):
        service.send_message(phone, str(response))
        return

    if response.response_type == "buttons" and response.buttons:
        if hasattr(service, 'send_buttons'):
            result = service.send_buttons(phone, response.text, response.buttons)
            if result.get('status') != 'error':
                return
            log.warn('send_buttons_failed_fallback_text',
                     message='Interactive buttons failed; sending plain text',
                     meta_result=str(result)[:200])
        options = "\n".join(
            f"{btn.get('id', i+1)}. {btn['title']}" for i, btn in enumerate(response.buttons)
        )
        service.send_message(phone, f"{response.text}\n\n{options}")

    elif response.response_type == "list" and response.list_sections:
        if hasattr(service, 'send_list'):
            result = service.send_list(
                phone, response.text, response.list_button_text, response.list_sections
            )
            if result.get('status') != 'error':
                return
            log.warn('send_list_failed_fallback_text',
                     message='Interactive list failed; sending plain text',
                     meta_result=str(result)[:200])
        for section in response.list_sections:
            rows = section.get('rows', [])
            options = "\n".join(
                f"{row.get('id', i+1)}. {row['title']}" for i, row in enumerate(rows)
            )
            service.send_message(phone, f"{response.text}\n\n{options}")

    else:
        service.send_message(phone, response.text)
