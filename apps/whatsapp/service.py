import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v18.0"


class WhatsAppService:
    """Real Meta WhatsApp Cloud API service."""

    def __init__(self):
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
        self.api_url = f"{GRAPH_API_URL}/{self.phone_number_id}/messages"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def send_message(self, to: str, text: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"[WhatsApp] Sent to {to}: {text[:50]}...")
        return response.json()

    def send_interactive_menu(self, to: str, body: str, buttons: list) -> dict:
        button_objects = [
            {"type": "reply", "reply": {"id": str(i + 1), "title": btn}}
            for i, btn in enumerate(buttons[:3])  # WhatsApp max 3 buttons
        ]
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": button_objects},
            },
        }
        response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
