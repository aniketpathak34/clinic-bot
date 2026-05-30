import json
import logging
import hmac
import hashlib
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


# ─── Startup warning ────────────────────────────────────────────────
# If the app secret is missing, the webhook will skip signature checks.
# That's fine for local dev but should NEVER be the case in production.
# Log it once at module import so it shows up in startup logs.
if not getattr(settings, 'META_APP_SECRET', ''):
    logger.warning(
        '[startup] META_APP_SECRET is not set — webhook signature verification '
        'is DISABLED. Anyone with the URL can POST to /api/webhook/whatsapp/. '
        'Set META_APP_SECRET in your env (Meta Dashboard → App Settings → Basic).'
    )


def _verify_meta_signature(request: HttpRequest, raw_body: bytes):
    """Verify Meta's X-Hub-Signature-256 header against the raw request body.

    Returns (True, '')  → signature valid OR verification skipped (no secret).
    Returns (False, reason) → reject the request with 403.

    Uses hmac.compare_digest (constant-time) to prevent timing attacks.
    """
    secret = getattr(settings, 'META_APP_SECRET', '')
    if not secret:
        # Skip mode for local dev — startup warning already logged
        return True, ''

    header = request.headers.get('X-Hub-Signature-256', '')
    if not header:
        return False, 'header_missing'
    if not header.startswith('sha256='):
        return False, 'header_malformed'

    received = header[len('sha256='):]
    expected = hmac.new(
        secret.encode('utf-8'),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(received, expected):
        return False, 'signature_mismatch'
    return True, ''


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
    """Receive incoming WhatsApp messages from Meta.

    Logs ONE RequestLog row per real user message (events buffered + flushed
    at the end). Status callbacks (sent/delivered/read) emit nothing — they
    early-exit before opening a trace.
    """
    import time as _time

    # ─── Signature verification (constant-time, before any processing) ───
    # MUST happen before we touch the body for JSON parsing, both because
    # we don't want to do work on an unauthenticated request and because
    # Django's request.body can only be read once.
    raw_body = request.body
    valid, reason = _verify_meta_signature(request, raw_body)
    if not valid:
        new_trace()
        log.error('webhook_signature_mismatch',
                  message=f'Webhook REJECTED: {reason}',
                  reason=reason,
                  has_header=bool(request.headers.get('X-Hub-Signature-256')),
                  remote_addr=request.META.get('REMOTE_ADDR', '')[:32],
                  user_agent=(request.headers.get('User-Agent', ''))[:80],
                  body_size=len(raw_body))
        log.flush(request_kind='webhook',
                  inbound_text=f'rejected:{reason}',
                  summary=f'Webhook signature rejected: {reason}')
        return HttpResponse('Forbidden', status=403)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {"status": "invalid_json"}

    phone, text, display_number = extract_message_from_webhook(payload)

    # Meta status callbacks (sent/delivered/read) — silent ack
    if not phone or not text:
        return {"status": "no_message"}

    # Real user message — open a trace + start the buffer
    new_trace()
    set_correlation(whatsapp_number=phone)
    started = _time.monotonic()

    clinic = Clinic.find_by_display_number(display_number) if display_number else None
    if not clinic:
        log.warn('webhook_unmatched_clinic',
                 message='No Clinic registered for this display_phone_number',
                 display_number=display_number, sender_digit10=phone[-10:])
        log.flush(inbound_text=text,
                  latency_ms=int((_time.monotonic() - started) * 1000))
        return {"status": "unknown_clinic"}

    set_correlation(clinic_id=clinic.id)
    log.event('webhook_received',
              message=f'Inbound from …{phone[-4:]} to {clinic.clinic_code}',
              clinic_code=clinic.clinic_code,
              sender_digit10=phone[-10:],
              text_preview=text[:60])

    try:
        response = handle_message(phone, text, clinic=clinic)
        send_bot_response(phone, response, clinic=clinic)
    except Exception as e:
        log.error('webhook_handler_crashed', exc=e,
                  message='Engine or send_bot_response raised — bot did NOT reply')
        log.flush(inbound_text=text,
                  latency_ms=int((_time.monotonic() - started) * 1000))
        return {"status": "error"}

    # One DB write — the consolidated row for this whole webhook
    log.flush(inbound_text=text,
              latency_ms=int((_time.monotonic() - started) * 1000))
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
