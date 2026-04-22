"""Patient conversation graph — routes incoming messages to the correct node function."""
import logging
from bot_locale.messages import get_msg
from apps.conversations.nodes.patient_nodes import (
    handle_language_select,
    handle_registration,
    handle_main_menu,
    handle_booking,
    start_booking,
    handle_cancel,
    handle_reschedule,
    view_appointments,
    handle_enquiry,
    _language_buttons,
    _main_menu_list,
)

logger = logging.getLogger(__name__)


def run_patient_graph(state, text: str):
    """Process one step of the patient conversation.

    Each incoming message runs exactly one step based on current_flow and step.
    State is persisted in Django DB (ConversationState model).
    Returns a BotResponse or string.
    """
    text_lower = text.strip().lower()

    # Global commands — work from any state
    if text_lower == 'menu':
        if state.language:
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            return _main_menu_list(state.language)

    # Route based on current flow
    flow = state.current_flow

    # No language on conversation state — decide between returning registered patient
    # (restore their saved language → straight to menu) vs truly new user (language picker).
    if not state.language:
        from apps.clinic.models import Patient
        patient = Patient.objects.filter(
            whatsapp_number=state.whatsapp_number, is_registered=True
        ).first()

        if patient and patient.language_preference:
            state.language = patient.language_preference
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            return _main_menu_list(state.language)

        state.current_flow = 'language_select'
        state.step = ''
        state.save()

        if flow == 'language_select':
            response, state = handle_language_select(state, text)
            return response
        # First message from a genuinely new user — show language buttons
        clinic_name = state.clinic.name if state.clinic else None
        return _language_buttons(clinic_name)

    # Registration flow (lazy — only when booking)
    if flow == 'registration':
        response, state = handle_registration(state, text)
        return response

    # Main menu — handle selection
    if flow == 'main_menu' or flow == '':
        state.current_flow = 'main_menu'
        response, state = handle_main_menu(state, text)
        return response

    # Booking flow
    if flow == 'booking':
        response, state = handle_booking(state, text)
        return response

    # Cancel flow
    if flow == 'cancel':
        response, state = handle_cancel(state, text)
        return response

    # Reschedule flow
    if flow == 'reschedule':
        response, state = handle_reschedule(state, text)
        return response

    # Enquiry
    if flow == 'enquiry':
        response, state = handle_enquiry(state, text)
        return response

    # Language selection (returning to it)
    if flow == 'language_select':
        response, state = handle_language_select(state, text)
        return response

    # Fallback
    return get_msg(state.language or 'en', 'error')
