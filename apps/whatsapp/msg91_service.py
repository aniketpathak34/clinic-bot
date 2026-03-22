"""MSG91 WhatsApp service integration.

Two endpoints:
1. Session messages: https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/
2. Template messages: https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/
"""
import json
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SESSION_URL = "https://control.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/"
TEMPLATE_URL = "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/"


class MSG91WhatsAppService:
    """MSG91 WhatsApp Cloud API service."""

    def __init__(self):
        self.auth_key = settings.MSG91_AUTH_KEY
        self.integrated_number = settings.MSG91_INTEGRATED_NUMBER
        self._headers = {
            "accept": "application/json",
            "authkey": self.auth_key,
            "content-type": "application/json",
        }

    def send_message(self, to: str, text: str) -> dict:
        """Send a plain text message."""
        body = {
            "integrated_number": self.integrated_number,
            "content_type": "text",
            "recipient_number": to,
            "text": text,
        }
        return self._post(SESSION_URL, body, to, text[:50])

    def send_buttons(self, to: str, body_text: str, buttons: list) -> dict:
        """Send interactive button message (max 3 buttons).

        buttons: list of {"id": "1", "title": "Book Appointment"}
        """
        button_objects = [
            {"type": "reply", "reply": {"id": str(btn.get("id", i+1)), "title": btn["title"][:20]}}
            for i, btn in enumerate(buttons[:3])
        ]

        payload = {
            "integrated_number": self.integrated_number,
            "content_type": "interactive",
            "recipient_number": to,
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": button_objects}
            }
        }
        return self._post(SESSION_URL, payload, to, f"buttons: {body_text[:30]}")

    def send_list(self, to: str, body_text: str, button_text: str, sections: list) -> dict:
        """Send interactive list message (up to 10 items).

        sections: [{"title": "Section", "rows": [{"id": "1", "title": "Option 1", "description": "..."}]}]
        """
        payload = {
            "integrated_number": self.integrated_number,
            "content_type": "interactive",
            "recipient_number": to,
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button": button_text[:20],
                    "sections": sections
                }
            }
        }
        return self._post(SESSION_URL, payload, to, f"list: {body_text[:30]}")

    def send_template(self, to: str, template_name: str, language: str = "en",
                      variables: dict = None) -> dict:
        """Send a pre-approved template message."""
        components = []
        if variables:
            parameters = [{"type": "text", "text": str(v)} for v in variables.values()]
            components.append({"type": "body", "parameters": parameters})

        payload = {
            "integrated_number": self.integrated_number,
            "content_type": "template",
            "payload": {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language, "policy": "deterministic"},
                    "components": components
                }
            }
        }

        headers = {"authkey": self.auth_key, "Content-Type": "application/json"}
        try:
            response = requests.post(TEMPLATE_URL, headers=headers, json=payload, timeout=10)
            print(f"[MSG91] Template response {response.status_code}: {response.text[:300]}")
            return response.json() if response.status_code == 200 else {"status": "error"}
        except requests.RequestException as e:
            logger.error(f"[MSG91 WhatsApp] Template failed: {e}")
            return {"status": "error", "message": str(e)}

    # Keep backward compatibility
    def send_interactive_menu(self, to: str, body: str, buttons: list) -> dict:
        """Backward compatible — converts to send_buttons."""
        btn_list = [{"id": str(i+1), "title": btn} for i, btn in enumerate(buttons)]
        return self.send_buttons(to, body, btn_list)

    def _post(self, url: str, body: dict, to: str, log_msg: str) -> dict:
        """Common POST with logging."""
        try:
            response = requests.post(url, headers=self._headers, json=body, timeout=10)
            print(f"[MSG91] Send response {response.status_code}: {response.text[:300]}")
            if response.status_code == 200:
                logger.info(f"[MSG91 WhatsApp] Sent to {to}: {log_msg}")
                return response.json()
            else:
                logger.error(f"[MSG91 WhatsApp] {response.status_code}: {response.text[:200]}")
                return {"status": "error", "code": response.status_code}
        except requests.RequestException as e:
            logger.error(f"[MSG91 WhatsApp] Failed: {e}")
            return {"status": "error", "message": str(e)}
