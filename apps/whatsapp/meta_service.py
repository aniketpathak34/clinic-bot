"""Meta WhatsApp Cloud API service — supports multi-clinic routing.

Each clinic has its own `phone_number_id` (Meta's internal ID for a WA number).
Optionally each clinic can override the access token; otherwise the shared
System User token from settings is used.

Instantiate with a Clinic to send from that clinic's number:
    service = MetaWhatsAppService(clinic=clinic)
    service.send_message("9198...", "Hi")

Without a clinic, falls back to META_DEFAULT_PHONE_NUMBER_ID — useful for
the mock/dev path and admin tasks.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class MetaWhatsAppService:
    """Meta WhatsApp Cloud API client bound to a single phone number."""

    def __init__(self, clinic=None, phone_number_id: str = None, access_token: str = None):
        if clinic is not None:
            phone_number_id = phone_number_id or clinic.phone_number_id
            access_token = access_token or clinic.access_token or settings.META_ACCESS_TOKEN
        else:
            phone_number_id = phone_number_id or settings.META_DEFAULT_PHONE_NUMBER_ID
            access_token = access_token or settings.META_ACCESS_TOKEN

        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.api_version = settings.META_GRAPH_API_VERSION
        self.api_url = (
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        )
        self._headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    # ─── public API ──────────────────────────────────────────────

    def send_message(self, to: str, text: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return self._post(payload, to, text[:50])

    def send_buttons(self, to: str, body_text: str, buttons: list) -> dict:
        """Interactive reply buttons. Max 3 buttons, title ≤ 20 chars."""
        button_objects = [
            {"type": "reply", "reply": {"id": str(btn.get("id", i + 1)), "title": btn["title"][:20]}}
            for i, btn in enumerate(buttons[:3])
        ]
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": button_objects},
            },
        }
        return self._post(payload, to, f"buttons: {body_text[:30]}")

    def send_list(self, to: str, body_text: str, button_text: str, sections: list) -> dict:
        """Interactive list. Up to 10 rows total across sections."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {"button": button_text[:20], "sections": sections},
            },
        }
        return self._post(payload, to, f"list: {body_text[:30]}")

    def send_template(self, to: str, template_name: str, language: str = "en",
                      variables: dict = None) -> dict:
        """Pre-approved template — required for messages outside the 24h window."""
        components = []
        if variables:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in variables.values()],
            })
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }
        return self._post(payload, to, f"template: {template_name}")

    # Back-compat shim — old code calls send_interactive_menu with a list of strings.
    def send_interactive_menu(self, to: str, body: str, buttons: list) -> dict:
        btns = [{"id": str(i + 1), "title": b} for i, b in enumerate(buttons)]
        return self.send_buttons(to, body, btns)

    # ─── internals ───────────────────────────────────────────────

    def _post(self, payload: dict, to: str, log_msg: str) -> dict:
        if not self.phone_number_id or not self.access_token:
            logger.error("[Meta] Missing phone_number_id or access_token — cannot send")
            return {"status": "error", "message": "missing_credentials"}
        try:
            resp = requests.post(self.api_url, headers=self._headers, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"[Meta] Sent to {to}: {log_msg}")
                return resp.json()
            logger.error(f"[Meta] {resp.status_code}: {resp.text[:300]}")
            return {"status": "error", "code": resp.status_code, "body": resp.text[:300]}
        except requests.RequestException as e:
            logger.error(f"[Meta] Request failed: {e}")
            return {"status": "error", "message": str(e)}
