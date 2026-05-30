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
from apps.observability import log
from apps.observability.context import set_correlation
from apps.utils.phone import normalize_phone, normalize_phone_safe

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

    # Canonicalize the sender phone so EVERY downstream lookup compares
    # canonical-vs-canonical. If the input is malformed, log + fall back to
    # a best-effort cleanup so we don't drop the message.
    try:
        phone = normalize_phone(phone)
    except ValueError as e:
        log.warn('phone_normalize_failed',
                 message=f'Could not canonicalize sender phone: {e}',
                 raw=phone[:30] if phone else '')
        phone = normalize_phone_safe(phone, phone or '')

    # Defense-in-depth: even if a caller forgets to set correlation,
    # every event from here on at least carries the sender phone + clinic.
    set_correlation(
        whatsapp_number=phone,
        clinic_id=(incoming_clinic.id if incoming_clinic else None),
    )

    # ONE state per (phone, clinic) — looking up by both means a patient who
    # also messages another clinic gets a fresh, independent conversation at
    # that other clinic. The composite UniqueConstraint on the model enforces
    # the invariant at the DB level.
    state, created = ConversationState.objects.get_or_create(
        whatsapp_number=phone,
        clinic=incoming_clinic,
        defaults={'user_type': 'unknown', 'context': {}},
    )
    if created:
        clinic_label = incoming_clinic.clinic_code if incoming_clinic else 'no_clinic'
        log.event('state_created',
                  message=f'First-ever message from …{phone[-4:]} to {clinic_label}')

    # Propagate flow/step into observability context so every downstream log
    # event automatically gets these fields attached.
    set_correlation(user_type=state.user_type or 'unknown',
                    flow=state.current_flow or '',
                    step=state.step or '')

    text_lower = text.strip().lower()

    # Reset commands
    if text_lower in ('reset', 'restart', 'start over'):
        log.event('state_reset', message='User issued reset command')
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
            log.event('flow_restart_to_main_menu',
                      message='Hi/hello mid-flow → reset to main menu',
                      previous_flow=state.current_flow, previous_step=state.step)
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            set_correlation(flow='main_menu', step='')
            from .nodes.patient_nodes import _main_menu_list
            return _main_menu_list(state.language)

    # --- STEP 1: Identify user type ---
    if state.user_type == 'unknown':
        doctor = Doctor.objects.filter(
            whatsapp_number=phone, is_registered=True
        ).select_related('clinic').first()

        if doctor:
            state.user_type = 'doctor'
            state.clinic = doctor.clinic
            state.save()
            set_correlation(user_type='doctor')
            log.event('identity_resolved',
                      message=f'Identified as doctor {doctor.name}',
                      resolved_type='doctor',
                      matched_by='exact_phone',
                      doctor_id=doctor.pk,
                      doctor_clinic_id=doctor.clinic_id,
                      doctor_clinic_code=doctor.clinic.clinic_code if doctor.clinic else None)
        elif incoming_clinic is not None:
            state.user_type = 'patient'
            state.save()
            set_correlation(user_type='patient')
            log.event('identity_resolved',
                      message=f'Identified as patient on {incoming_clinic.clinic_code}',
                      resolved_type='patient',
                      matched_by='inbound_clinic')
        else:
            user_type, resolved_clinic = identify_user(phone, text)
            state.user_type = user_type
            if resolved_clinic:
                state.clinic = resolved_clinic
            state.save()
            set_correlation(user_type=user_type)
            log.event('identity_resolved',
                      message='Legacy clinic-code resolution',
                      resolved_type=user_type,
                      matched_by='legacy_clinic_code',
                      resolved_clinic_code=(resolved_clinic.clinic_code
                                            if resolved_clinic else None))
            if user_type == 'unknown':
                log.warn('identity_unknown_prompt_clinic_code',
                         message='No doctor + no clinic resolvable — asking for clinic code')
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
            log.event('patient_clinic_resolved_late',
                      message='Patient sent clinic code mid-conversation',
                      resolved_clinic_code=resolved_clinic.clinic_code)
            state.clinic = resolved_clinic
            state.save()
            set_correlation(clinic_id=resolved_clinic.id)
        else:
            log.event('patient_awaiting_clinic_code',
                      message='Patient still without clinic — asking for code')
            return BotResponse.as_text(
                "Please send the clinic code to continue.\n"
                "Example: *TC01*"
            )

    # --- STEP 3: Route to correct graph ---
    # Debug-only: this fires on every message and is implicit from the next
    # downstream event (handle_set_availability, main_menu_choice, etc).
    # Keeping it at debug means it lands in the DB only if you bump the level,
    # but the downstream events tell the routing story regardless.
    log.debug('route_dispatched', target=state.user_type)
    if state.user_type == 'doctor':
        response = run_doctor_graph(state, text)
    else:
        response = run_patient_graph(state, text)

    if isinstance(response, str):
        return BotResponse.as_text(response)
    return response
