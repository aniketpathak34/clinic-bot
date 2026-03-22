import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# In-memory store for mock messages
_mock_messages = defaultdict(list)


class MockWhatsAppService:
    """Mock WhatsApp service that stores messages in memory for testing."""

    def send_message(self, to: str, text: str) -> dict:
        msg = {'to': to, 'text': text, 'type': 'text'}
        _mock_messages[to].append(msg)
        logger.info(f"[MOCK WhatsApp] To: {to} | Message: {text}")
        return {'status': 'sent', 'mock': True}

    def send_buttons(self, to: str, body_text: str, buttons: list) -> dict:
        msg = {'to': to, 'body': body_text, 'buttons': buttons, 'type': 'buttons'}
        _mock_messages[to].append(msg)
        logger.info(f"[MOCK WhatsApp] To: {to} | Buttons: {body_text}")
        return {'status': 'sent', 'mock': True}

    def send_list(self, to: str, body_text: str, button_text: str, sections: list) -> dict:
        msg = {'to': to, 'body': body_text, 'button_text': button_text, 'sections': sections, 'type': 'list'}
        _mock_messages[to].append(msg)
        logger.info(f"[MOCK WhatsApp] To: {to} | List: {body_text}")
        return {'status': 'sent', 'mock': True}

    def send_interactive_menu(self, to: str, body: str, buttons: list) -> dict:
        return self.send_buttons(to, body, [{"id": str(i+1), "title": btn} for i, btn in enumerate(buttons)])

    @staticmethod
    def get_messages(phone=None):
        if phone:
            return list(_mock_messages.get(phone, []))
        return dict(_mock_messages)

    @staticmethod
    def clear_messages():
        _mock_messages.clear()
