from importlib import import_module
from django.conf import settings


def get_whatsapp_service():
    """Factory: returns the configured WhatsApp service instance."""
    module_path, class_name = settings.WHATSAPP_SERVICE_CLASS.rsplit('.', 1)
    module = import_module(module_path)
    service_class = getattr(module, class_name)
    return service_class()


def extract_message_from_webhook(payload: dict) -> tuple:
    """Extract phone number and message text from webhook payload.
    Supports both MSG91 and Meta WhatsApp Cloud API formats.
    Returns (phone_number, message_text) or (None, None) if not a message.
    """
    # Try MSG91 format first
    phone, text = _extract_msg91(payload)
    if phone and text:
        return phone, text

    # Fallback to Meta format
    return _extract_meta(payload)


def _extract_msg91(payload: dict) -> tuple:
    """Extract from MSG91 webhook payload.

    Actual MSG91 inbound payload:
    {
        "customerNumber": "917030344210",
        "text": "Hi",
        "contentType": "text",
        "messageType": "text",
        "integratedNumber": "917020162229",
        "customerName": "Aniket Pathak",
        ...
    }
    """
    try:
        # MSG91 payloads always have customerNumber and integratedNumber
        phone = payload.get('customerNumber', '')
        integrated = payload.get('integratedNumber', '')

        if not phone or not integrated:
            return None, None

        # Clean phone number
        phone = phone.lstrip('+')

        # Get message text based on content type
        content_type = payload.get('contentType', '')
        message_type = payload.get('messageType', '')

        if message_type == 'interactive' or content_type == 'interactive':
            # User tapped a button or list item — extract the ID or title
            interactive = payload.get('interactive', '')
            if interactive:
                import json
                try:
                    inter_data = json.loads(interactive) if isinstance(interactive, str) else interactive
                    # Button reply
                    if 'button_reply' in inter_data:
                        text = inter_data['button_reply'].get('id', '') or inter_data['button_reply'].get('title', '')
                    # List reply
                    elif 'list_reply' in inter_data:
                        text = inter_data['list_reply'].get('id', '') or inter_data['list_reply'].get('title', '')
                    else:
                        text = payload.get('text', '') or payload.get('button', '')
                except (json.JSONDecodeError, TypeError):
                    text = payload.get('text', '') or payload.get('button', '')
            else:
                text = payload.get('text', '') or payload.get('button', '')
        elif content_type in ('text', 'button') or message_type == 'text':
            text = payload.get('text', '')
        else:
            text = payload.get('text', '')

        if text:
            return phone, text.strip()
        return None, None

    except (KeyError, AttributeError):
        return None, None


def _extract_meta(payload: dict) -> tuple:
    """Extract from Meta WhatsApp Cloud API webhook payload."""
    try:
        entry = payload.get('entry', [{}])[0]
        changes = entry.get('changes', [{}])[0]
        value = changes.get('value', {})
        messages = value.get('messages', [])
        if not messages:
            return None, None
        message = messages[0]
        phone = message.get('from', '')
        # Handle text messages
        if message.get('type') == 'text':
            text = message.get('text', {}).get('body', '')
        # Handle interactive button replies
        elif message.get('type') == 'interactive':
            interactive = message.get('interactive', {})
            if interactive.get('type') == 'button_reply':
                text = interactive.get('button_reply', {}).get('title', '')
            else:
                text = interactive.get('list_reply', {}).get('title', '')
        else:
            text = ''
        return phone, text
    except (IndexError, KeyError):
        return None, None
