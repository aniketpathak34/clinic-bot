import logging
from django.conf import settings
from django.http import HttpResponse, HttpRequest
from ninja import Router

from .utils import extract_message_from_webhook, get_whatsapp_service
from apps.conversations.engine import handle_message
from apps.conversations.response import BotResponse

logger = logging.getLogger(__name__)

router = Router()


@router.get("/whatsapp/")
def whatsapp_webhook_verify(request: HttpRequest):
    """Meta WhatsApp Cloud API webhook verification."""
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if mode == 'subscribe' and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return HttpResponse(challenge, content_type='text/plain')
    return HttpResponse('Forbidden', status=403)


@router.post("/whatsapp/")
def whatsapp_webhook_receive(request: HttpRequest):
    """Receive incoming WhatsApp messages."""
    import json
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return {"status": "invalid_json"}

    print(f"[WEBHOOK] Raw payload: {json.dumps(payload)[:500]}")
    phone, text = extract_message_from_webhook(payload)
    print(f"[WEBHOOK] Extracted — phone: {phone}, text: {text}")

    if not phone or not text:
        return {"status": "no_message"}

    logger.info(f"Incoming message from {phone}: {text}")

    response = handle_message(phone, text)
    send_bot_response(phone, response)

    return {"status": "ok"}


def send_bot_response(phone: str, response):
    """Send the appropriate message type based on BotResponse.

    Tries interactive (buttons/list) first, falls back to plain text.
    """
    service = get_whatsapp_service()

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
        # Fallback to text
        options = "\n".join(f"{btn.get('id', i+1)}. {btn['title']}" for i, btn in enumerate(response.buttons))
        service.send_message(phone, f"{response.text}\n\n{options}")

    elif response.response_type == "list" and response.list_sections:
        if hasattr(service, 'send_list'):
            result = service.send_list(phone, response.text, response.list_button_text, response.list_sections)
            if result.get('status') != 'error':
                return
        # Fallback to text
        for section in response.list_sections:
            rows = section.get('rows', [])
            options = "\n".join(f"{row.get('id', i+1)}. {row['title']}" for i, row in enumerate(rows))
            service.send_message(phone, f"{response.text}\n\n{options}")

    else:
        service.send_message(phone, response.text)
