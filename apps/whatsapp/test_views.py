import logging
from ninja import Router, Schema
from typing import Optional

from .utils import get_whatsapp_service
from .mock_service import MockWhatsAppService
from apps.conversations.engine import handle_message
from apps.conversations.models import ConversationState

logger = logging.getLogger(__name__)

router = Router()


class SendMessageIn(Schema):
    from_number: str  # aliased from "from" in the endpoint
    message: str


@router.post("/send/")
def test_send_message(request):
    """Dev-only: Simulate an incoming WhatsApp message.
    POST {"from": "919876543210", "message": "Hi"}
    """
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON"}

    phone = data.get('from', '')
    text = data.get('message', '')

    if not phone or not text:
        from ninja.errors import HttpError
        raise HttpError(400, "Both 'from' and 'message' are required")

    from apps.conversations.response import BotResponse
    from .views import send_bot_response

    response = handle_message(phone, text)
    send_bot_response(phone, response)

    # Extract text for display
    bot_reply = response.text if isinstance(response, BotResponse) else str(response)

    return {
        "from": phone,
        "message": text,
        "bot_reply": bot_reply,
    }


@router.get("/messages/")
def test_get_messages(request, phone: Optional[str] = None):
    """Dev-only: View all mock-sent outbound messages."""
    messages = MockWhatsAppService.get_messages(phone)
    return {"messages": messages}


@router.get("/conversation/{phone}/")
def test_conversation_state(request, phone: str):
    """Dev-only: View conversation state for a phone number."""
    try:
        state = ConversationState.objects.get(whatsapp_number=phone)
        return {
            "whatsapp_number": state.whatsapp_number,
            "user_type": state.user_type,
            "current_flow": state.current_flow,
            "step": state.step,
            "context": state.context,
            "language": state.language,
            "updated_at": state.updated_at.isoformat(),
        }
    except ConversationState.DoesNotExist:
        from ninja.errors import HttpError
        raise HttpError(404, "No conversation found for this number")


@router.post("/clear/")
def test_clear_messages(request):
    """Dev-only: Clear all mock messages."""
    MockWhatsAppService.clear_messages()
    return {"status": "cleared"}
