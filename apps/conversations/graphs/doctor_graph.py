"""Doctor conversation graph — for pre-registered doctors only.

Doctors are added via Django Admin. When a doctor messages the bot,
they are identified by phone number and get their menu directly.
"""
import logging
from apps.conversations.nodes.doctor_nodes import (
    _doctor_menu_list,
    handle_doctor_menu,
    handle_set_availability,
)

logger = logging.getLogger(__name__)


def run_doctor_graph(state, text: str):
    """Process one step of the doctor conversation."""
    text_lower = text.strip().lower()

    # Global commands
    if text_lower in ('menu', 'hi', 'hello'):
        state.current_flow = 'doctor_menu'
        state.step = ''
        state.context = {}
        state.save()
        from apps.clinic.models import Doctor
        doctor = Doctor.objects.filter(
            whatsapp_number=state.whatsapp_number, is_registered=True
        ).first()
        return _doctor_menu_list(doctor.name if doctor else None)

    flow = state.current_flow

    # First message — show welcome + menu
    if flow == '':
        state.current_flow = 'doctor_menu'
        state.save()
        from apps.clinic.models import Doctor
        doctor = Doctor.objects.filter(
            whatsapp_number=state.whatsapp_number, is_registered=True
        ).first()
        return _doctor_menu_list(doctor.name if doctor else None)

    # Doctor menu — handle selection
    if flow == 'doctor_menu':
        response, state = handle_doctor_menu(state, text)
        return response

    # Set availability
    if flow == 'set_availability':
        response, state = handle_set_availability(state, text)
        return response

    # Fallback — show menu
    return _doctor_menu_list()
