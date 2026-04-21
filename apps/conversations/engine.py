"""
Core conversation engine — dispatches incoming messages to the correct flow.

Multi-clinic architecture:
- Each clinic has its own Meta WhatsApp number (phone_number_id).
- The webhook resolves the clinic from metadata.display_phone_number and
  passes it into handle_message as `incoming_clinic`. That clinic is
  authoritative — patients never need to send a clinic code.
- Doctors are identified by their whatsapp_number belonging to a Doctor row.
"""
import logging

from apps.clinic.models import Doctor

from .models import ConversationState
from .response import BotResponse
from .graphs.identification import identify_user, try_parse_clinic_code
from .graphs.patient_graph import run_patient_graph
from .graphs.doctor_graph import run_doctor_graph

logger = logging.getLogger(__name__)


def handle_message(phone: str, text: str, clinic=None):
    """Main entry point: process an incoming WhatsApp message.

    `clinic` is the Clinic that received the message, resolved from Meta's
    webhook metadata.display_phone_number. When provided it is authoritative.
    """
    incoming_clinic = clinic

    state, _ = ConversationState.objects.get_or_create(
        whatsapp_number=phone,
        defaults={'user_type': 'unknown', 'context': {}},
    )

    # The inbound number is authoritative — trust it over any stale state.
    if incoming_clinic is not None and state.clinic_id != incoming_clinic.id:
        state.clinic = incoming_clinic
        state.save(update_fields=['clinic'])

    text_lower = text.strip().lower()

    # Reset commands
    if text_lower in ('reset', 'restart', 'start over'):
        state.reset()
        state.user_type = 'unknown'
        state.language = ''
        if incoming_clinic is not None:
            state.clinic = incoming_clinic
        state.save()
        return BotResponse.as_text("Conversation reset. Send *hi* to start again.")

    # Hi/Hello mid-flow → restart to main menu (keep clinic + language)
    if text_lower in ('hi', 'hello', 'hey', 'start') and state.current_flow not in ('', 'main_menu', 'language_select'):
        if state.language:
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            from .nodes.patient_nodes import _main_menu_list
            return _main_menu_list(state.language)

    # --- STEP 1: Identify user type ---
    if state.user_type == 'unknown':
        # Doctor lookup first — works regardless of which clinic number they messaged
        doctor = Doctor.objects.filter(
            whatsapp_number=phone, is_registered=True
        ).select_related('clinic').first()

        if doctor:
            state.user_type = 'doctor'
            state.clinic = doctor.clinic
            state.save()
        elif incoming_clinic is not None:
            # Clinic already known from the number they messaged → treat as patient
            state.user_type = 'patient'
            state.save()
        else:
            # Fallback to legacy identification (clinic-code flow)
            user_type, resolved_clinic = identify_user(phone, text)
            state.user_type = user_type
            if resolved_clinic:
                state.clinic = resolved_clinic
            state.save()
            if user_type == 'unknown':
                return BotResponse.as_text(
                    "Welcome! 👋\n\n"
                    "To book an appointment, scan the QR code at the clinic "
                    "or send the clinic code.\n\n"
                    "Example: Send *TC01*"
                )

    # --- STEP 2: Patient still without clinic — ask for clinic code (legacy path) ---
    if state.user_type == 'patient' and not state.clinic:
        resolved_clinic = try_parse_clinic_code(text)
        if resolved_clinic:
            state.clinic = resolved_clinic
            state.save()
        else:
            return BotResponse.as_text(
                "Please send the clinic code to continue.\n"
                "Example: *TC01*"
            )

    # --- STEP 3: Route to correct graph ---
    if state.user_type == 'doctor':
        response = run_doctor_graph(state, text)
    else:
        response = run_patient_graph(state, text)

    if isinstance(response, str):
        return BotResponse.as_text(response)
    return response
