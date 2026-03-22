"""
Core conversation engine — dispatches incoming messages to the correct flow.

New architecture:
- Patient first message contains clinic code (from QR/link)
- Bot identifies clinic → scopes all actions to that clinic
- Doctors are pre-registered via admin (no self-registration)
"""
import logging
from .models import ConversationState
from .response import BotResponse
from .graphs.identification import identify_user, try_parse_clinic_code
from .graphs.patient_graph import run_patient_graph
from .graphs.doctor_graph import run_doctor_graph

logger = logging.getLogger(__name__)


def handle_message(phone: str, text: str):
    """Main entry point: process an incoming WhatsApp message."""

    # Load or create conversation state
    state, created = ConversationState.objects.get_or_create(
        whatsapp_number=phone,
        defaults={'user_type': 'unknown', 'context': {}}
    )

    text_lower = text.strip().lower()

    # Check for reset commands
    if text_lower in ('reset', 'restart', 'start over'):
        state.reset()
        state.user_type = 'unknown'
        state.language = ''
        state.save()
        return BotResponse.as_text(
            "Conversation reset.\n\n"
            "To book an appointment, scan the QR code at the clinic "
            "or send the clinic code."
        )

    # "Hi/Hello" mid-flow → restart to main menu (keep clinic + language)
    if text_lower in ('hi', 'hello', 'hey', 'start') and state.current_flow not in ('', 'main_menu', 'language_select'):
        if state.language and state.clinic:
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            from .nodes.patient_nodes import _main_menu_list
            return _main_menu_list(state.language)
        elif state.language:
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            from .nodes.patient_nodes import _main_menu_list
            return _main_menu_list(state.language)

    # --- STEP 1: Identify user if unknown ---
    if state.user_type == 'unknown':
        user_type, clinic = identify_user(phone, text)
        state.user_type = user_type
        if clinic:
            state.clinic = clinic
        state.save()

        # If still unknown (no clinic code, not a known user)
        if user_type == 'unknown':
            return BotResponse.as_text(
                "Welcome! 👋\n\n"
                "To book an appointment, please scan the QR code at the clinic "
                "or send the clinic code.\n\n"
                "Example: Send *TC01*"
            )

    # --- STEP 2: Patient without clinic — ask for clinic code ---
    if state.user_type == 'patient' and not state.clinic:
        # Try to parse clinic code from current message
        clinic = try_parse_clinic_code(text)
        if clinic:
            state.clinic = clinic
            state.save()
        else:
            return BotResponse.as_text(
                "Please send the clinic code to continue.\n\n"
                "You can find it on the clinic's QR code or card.\n"
                "Example: *TC01*"
            )

    # --- STEP 3: Route to correct graph ---
    if state.user_type == 'doctor':
        response = run_doctor_graph(state, text)
    else:
        response = run_patient_graph(state, text)

    # Ensure we always return a BotResponse
    if isinstance(response, str):
        return BotResponse.as_text(response)
    return response
