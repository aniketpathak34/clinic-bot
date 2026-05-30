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
    """Dev-only: View conversation states for a phone number across all clinics.

    A patient can have one state per clinic now — this returns every state row
    that exists for the given phone, ordered by most-recently updated.
    """
    states = (ConversationState.objects.filter(whatsapp_number=phone)
                                       .select_related('clinic')
                                       .order_by('-updated_at'))
    if not states.exists():
        from ninja.errors import HttpError
        raise HttpError(404, "No conversations found for this number")
    return {
        "whatsapp_number": phone,
        "states": [
            {
                "clinic_code":  (s.clinic.clinic_code if s.clinic else None),
                "clinic_id":    s.clinic_id,
                "user_type":    s.user_type,
                "current_flow": s.current_flow,
                "step":         s.step,
                "context":      s.context,
                "language":     s.language,
                "updated_at":   s.updated_at.isoformat(),
            }
            for s in states
        ],
    }


@router.post("/clear/")
def test_clear_messages(request):
    """Dev-only: Clear all mock messages."""
    MockWhatsAppService.clear_messages()
    return {"status": "cleared"}
