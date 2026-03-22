"""Bot response types for WhatsApp interactive messages."""


class BotResponse:
    """Represents a bot reply — can be text, buttons, or list."""

    def __init__(self, text: str, response_type: str = "text",
                 buttons: list = None, list_sections: list = None,
                 list_button_text: str = "Choose"):
        self.text = text
        self.response_type = response_type  # "text", "buttons", "list"
        self.buttons = buttons or []        # [{"id": "1", "title": "Option"}]
        self.list_sections = list_sections or []
        self.list_button_text = list_button_text

    @staticmethod
    def as_text(text: str):
        return BotResponse(text=text, response_type="text")

    @staticmethod
    def as_buttons(body: str, buttons: list):
        """buttons: [{"id": "1", "title": "Book Appt"}, ...]  (max 3)"""
        return BotResponse(text=body, response_type="buttons", buttons=buttons[:3])

    @staticmethod
    def as_list(body: str, button_text: str, rows: list):
        """rows: [{"id": "1", "title": "Option", "description": "desc"}, ...]  (max 10)"""
        sections = [{"title": "Options", "rows": rows[:10]}]
        return BotResponse(text=body, response_type="list",
                          list_sections=sections, list_button_text=button_text)
