"""Meta WhatsApp Cloud API helpers."""
from importlib import import_module
from django.conf import settings


def get_whatsapp_service(clinic=None):
    """Factory: returns a service instance bound to the given clinic.

    - If WHATSAPP_SERVICE_CLASS points to the mock, clinic is ignored.
    - For the Meta service, clinic supplies phone_number_id + access_token.
    - If clinic is None, falls back to settings.META_DEFAULT_PHONE_NUMBER_ID.
    """
    module_path, class_name = settings.WHATSAPP_SERVICE_CLASS.rsplit('.', 1)
    module = import_module(module_path)
    service_class = getattr(module, class_name)

    try:
        return service_class(clinic=clinic)
    except TypeError:
        # Mock or older service without clinic kwarg
        return service_class()


def extract_message_from_webhook(payload: dict) -> tuple:
    """Extract (patient_phone, text, display_phone_number) from a Meta webhook.

    display_phone_number is the clinic's WhatsApp number that received the message —
    used to look up which clinic this conversation belongs to in multi-clinic mode.

    Returns (None, None, None) if the payload is not a user message
    (e.g. a delivery/read status callback).
    """
    try:
        entry = payload.get('entry', [{}])[0]
        changes = entry.get('changes', [{}])[0]
        value = changes.get('value', {})

        # Clinic's WA number (the one receiving the message)
        metadata = value.get('metadata', {})
        display_number = metadata.get('display_phone_number', '').lstrip('+')

        messages = value.get('messages', [])
        if not messages:
            return None, None, display_number or None

        message = messages[0]
        phone = message.get('from', '')
        msg_type = message.get('type')

        if msg_type == 'text':
            text = message.get('text', {}).get('body', '')
        elif msg_type == 'interactive':
            interactive = message.get('interactive', {})
            if interactive.get('type') == 'button_reply':
                reply = interactive.get('button_reply', {})
                text = reply.get('id') or reply.get('title', '')
            elif interactive.get('type') == 'list_reply':
                reply = interactive.get('list_reply', {})
                text = reply.get('id') or reply.get('title', '')
            else:
                text = ''
        elif msg_type == 'button':
            # Template button reply
            text = message.get('button', {}).get('payload', '') or message.get('button', {}).get('text', '')
        else:
            text = ''

        return phone or None, (text.strip() if text else None), display_number or None

    except (IndexError, KeyError, AttributeError):
        return None, None, None
