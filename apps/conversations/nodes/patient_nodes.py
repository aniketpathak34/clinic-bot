"""Node functions for the patient conversation flow — all responses interactive."""
import logging
from datetime import date, datetime

from apps.clinic.models import Doctor, Patient, AvailableSlot, Appointment
from apps.whatsapp.utils import get_whatsapp_service
from bot_locale.messages import get_msg
from apps.conversations.nlp import parse_menu_choice, parse_natural_date
from apps.conversations.response import BotResponse

logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    '1': 'en', '2': 'hi', '3': 'mr',
    'english': 'en', 'hindi': 'hi', 'marathi': 'mr',
    'हिंदी': 'hi', 'मराठी': 'mr',
}


# ─── Interactive Response Builders ───────────────────────────────

def _language_buttons():
    return BotResponse.as_buttons(
        "Welcome! Please choose your language:",
        [
            {"id": "1", "title": "English"},
            {"id": "2", "title": "हिंदी"},
            {"id": "3", "title": "मराठी"},
        ]
    )


def _main_menu_list(lang):
    labels = {
        'en': {"body": "How can I help you today?", "btn": "Choose Option",
               "opts": ["Book Appointment", "Reschedule", "Cancel Appointment", "My Appointments", "Enquiry"]},
        'hi': {"body": "मैं आपकी कैसे मदद कर सकता हूँ?", "btn": "विकल्प चुनें",
               "opts": ["अपॉइंटमेंट बुक करें", "अपॉइंटमेंट बदलें", "अपॉइंटमेंट रद्द करें", "मेरी अपॉइंटमेंट", "पूछताछ"]},
        'mr': {"body": "मी तुम्हाला कशी मदत करू शकतो?", "btn": "पर्याय निवडा",
               "opts": ["अपॉइंटमेंट बुक करा", "अपॉइंटमेंट बदला", "अपॉइंटमेंट रद्द करा", "माझ्या अपॉइंटमेंट", "चौकशी"]},
    }
    l = labels.get(lang, labels['en'])
    rows = [{"id": str(i+1), "title": opt} for i, opt in enumerate(l["opts"])]
    return BotResponse.as_list(l["body"], l["btn"], rows)


def _with_menu(lang, prefix_text):
    """Return a text message followed by interactive main menu."""
    menu = _main_menu_list(lang)
    menu.text = f"{prefix_text}\n\n{menu.text}"
    return menu


def _appointment_list(lang, appointments, flow_type):
    """Build interactive list from appointments for cancel/reschedule."""
    labels = {
        'cancel': {
            'en': ("Which appointment to cancel?", "Select"),
            'hi': ("कौन सी अपॉइंटमेंट रद्द करनी है?", "चुनें"),
            'mr': ("कोणती अपॉइंटमेंट रद्द करायची?", "निवडा"),
        },
        'reschedule': {
            'en': ("Which appointment to reschedule?", "Select"),
            'hi': ("कौन सी अपॉइंटमेंट बदलनी है?", "चुनें"),
            'mr': ("कोणती अपॉइंटमेंट बदलायची?", "निवडा"),
        }
    }
    body, btn = labels.get(flow_type, labels['cancel']).get(lang, labels['cancel']['en'])
    rows = [
        {
            "id": str(i+1),
            "title": f"Dr. {a.doctor.name}",
            "description": f"{a.slot.date.strftime('%d-%b')} at {a.slot.time.strftime('%I:%M %p')}"
        }
        for i, a in enumerate(appointments)
    ]
    return BotResponse.as_list(body, btn, rows)


def _slot_list(lang, slots, doctor_name, date_str):
    """Build interactive list for time slot selection."""
    body = {
        'en': f'Available slots for Dr. {doctor_name} on {date_str}:',
        'hi': f'Dr. {doctor_name} की {date_str} को उपलब्ध समय:',
        'mr': f'Dr. {doctor_name} यांची {date_str} रोजी उपलब्ध वेळ:',
    }.get(lang, f'Slots for Dr. {doctor_name}:')
    btn = {'en': 'Choose Time', 'hi': 'समय चुनें', 'mr': 'वेळ निवडा'}.get(lang, 'Choose Time')
    rows = [{"id": str(i+1), "title": s.time.strftime('%I:%M %p')} for i, s in enumerate(slots)]
    return BotResponse.as_list(body, btn, rows)


def _doctor_list(lang, doctors):
    """Build interactive list for doctor selection."""
    body = {'en': 'Select a doctor:', 'hi': 'डॉक्टर चुनें:', 'mr': 'डॉक्टर निवडा:'}.get(lang, 'Select a doctor:')
    btn = {'en': 'Choose Doctor', 'hi': 'डॉक्टर चुनें', 'mr': 'डॉक्टर निवडा'}.get(lang, 'Choose Doctor')
    rows = [
        {"id": str(i+1), "title": f"Dr. {d.name}", "description": d.get_specialty_display()}
        for i, d in enumerate(doctors)
    ]
    return BotResponse.as_list(body, btn, rows)


def _date_list(lang, doctor_id, doctor_name):
    """Build interactive list of available dates for a doctor (next 10 dates with slots)."""
    from django.db.models import Count

    available_dates = (
        AvailableSlot.objects
        .filter(doctor_id=doctor_id, is_booked=False, date__gte=date.today())
        .values('date')
        .annotate(slot_count=Count('id'))
        .order_by('date')[:10]
    )

    if not available_dates:
        return None

    # Day names for display
    day_names_en = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    day_names_hi = ['सोम', 'मंगल', 'बुध', 'गुरु', 'शुक्र', 'शनि', 'रवि']
    day_names_mr = ['सोम', 'मंगळ', 'बुध', 'गुरु', 'शुक्र', 'शनि', 'रवि']
    days = {'en': day_names_en, 'hi': day_names_hi, 'mr': day_names_mr}.get(lang, day_names_en)

    slot_word = {'en': 'slots', 'hi': 'स्लॉट', 'mr': 'स्लॉट'}.get(lang, 'slots')

    rows = []
    for item in available_dates:
        d = item['date']
        count = item['slot_count']
        day_name = days[d.weekday()]
        rows.append({
            "id": d.strftime('%d-%b-%Y'),
            "title": f"{day_name}, {d.strftime('%d %b %Y')}",
            "description": f"{count} {slot_word} available"
        })

    body = {
        'en': f'Available dates for Dr. {doctor_name}:',
        'hi': f'Dr. {doctor_name} की उपलब्ध तारीखें:',
        'mr': f'Dr. {doctor_name} यांच्या उपलब्ध तारखा:',
    }.get(lang, f'Available dates for Dr. {doctor_name}:')
    btn = {'en': 'Choose Date', 'hi': 'तारीख चुनें', 'mr': 'तारीख निवडा'}.get(lang, 'Choose Date')

    return BotResponse.as_list(body, btn, rows)


# ─── Doctor Notifications ────────────────────────────────────────

def _notify_doctor(event: str, patient_name: str, doctor: Doctor, slot_date: str, slot_time: str):
    """Send instant WhatsApp notification to doctor (sent from doctor's clinic number)."""
    try:
        service = get_whatsapp_service(clinic=doctor.clinic)
        if event == 'booked':
            msg = (
                f"🔔 *New Appointment Booked!*\n\n"
                f"Patient: {patient_name}\n"
                f"Date: {slot_date}\n"
                f"Time: {slot_time}\n\n"
                f"Please ensure your availability."
            )
        elif event == 'cancelled':
            msg = (
                f"❌ *Appointment Cancelled*\n\n"
                f"Patient: {patient_name}\n"
                f"Date: {slot_date}\n"
                f"Time: {slot_time}\n\n"
                f"This slot is now available again."
            )
        elif event == 'rescheduled':
            msg = (
                f"🔄 *Appointment Rescheduled*\n\n"
                f"Patient: {patient_name}\n"
                f"New Date: {slot_date}\n"
                f"New Time: {slot_time}"
            )
        else:
            return

        service.send_message(doctor.whatsapp_number, msg)
        logger.info(f"Doctor {doctor.name} notified: {event}")
    except Exception as e:
        logger.error(f"Failed to notify doctor {doctor.name}: {e}")


# ─── Helpers ─────────────────────────────────────────────────────

def _find_doctor(text, doctor_ids):
    """Find doctor by number or name from interactive list tap."""
    try:
        idx = int(text.strip()) - 1
        if 0 <= idx < len(doctor_ids):
            return Doctor.objects.get(id=doctor_ids[idx])
    except (ValueError, Doctor.DoesNotExist):
        pass
    name_query = text.strip().replace('Dr. ', '').replace('Dr ', '')
    return Doctor.objects.filter(id__in=doctor_ids, name__icontains=name_query).first()


def _find_date(text, doctor_id):
    """Find date from interactive list tap (title like 'Mon, 25 Mar 2026') or typed text."""
    # Try parsing the ID format first (dd-Mon-YYYY)
    for fmt in ['%d-%b-%Y', '%d-%B-%Y', '%d-%m-%Y', '%d/%m/%Y']:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue

    # Try parsing title format like "Mon, 25 Mar 2026"
    clean = text.strip()
    # Remove day prefix like "Mon, " or "सोम, "
    if ', ' in clean:
        clean = clean.split(', ', 1)[1]
    for fmt in ['%d %b %Y', '%d %B %Y', '%d-%b-%Y', '%d-%b']:
        try:
            parsed = datetime.strptime(clean, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=date.today().year)
            return parsed.date()
        except ValueError:
            continue

    # Fallback to NLP parser
    lang_name = 'English'
    return parse_natural_date(text, lang_name)


def _find_slot(text, slot_ids):
    """Find slot by number or time text from interactive list tap."""
    try:
        idx = int(text.strip()) - 1
        if 0 <= idx < len(slot_ids):
            return AvailableSlot.objects.get(id=slot_ids[idx], is_booked=False)
    except (ValueError, AvailableSlot.DoesNotExist):
        pass
    time_text = text.strip().upper()
    for sid in slot_ids:
        try:
            s = AvailableSlot.objects.get(id=sid, is_booked=False)
            if s.time.strftime('%I:%M %p').upper() == time_text:
                return s
        except AvailableSlot.DoesNotExist:
            continue
    return None


def _find_appointment(text, appt_ids):
    """Find appointment by number or doctor name from interactive list tap."""
    try:
        idx = int(text.strip()) - 1
        if 0 <= idx < len(appt_ids):
            return Appointment.objects.select_related('doctor', 'slot').get(id=appt_ids[idx])
    except (ValueError, Appointment.DoesNotExist):
        pass
    name_query = text.strip().replace('Dr. ', '').replace('Dr ', '')
    return Appointment.objects.filter(
        id__in=appt_ids, doctor__name__icontains=name_query
    ).select_related('doctor', 'slot').first()


# ─── Flow Handlers ───────────────────────────────────────────────

def handle_language_select(state, text):
    choice = text.strip().lower()
    lang = LANGUAGE_MAP.get(choice)
    if not lang:
        return _language_buttons(), state
    state.language = lang
    state.current_flow = 'main_menu'
    state.step = ''
    state.context = {}
    state.save()
    return _main_menu_list(lang), state


def handle_registration(state, text):
    lang = state.language or 'en'
    context = state.context or {}

    if state.step == 'ask_name':
        name = text.strip()
        if not name or len(name) < 2:
            return get_msg(lang, 'ask_name'), state
        context['name'] = name
        state.context = context
        state.step = 'ask_age'
        state.save()
        return get_msg(lang, 'ask_age', name=name), state

    elif state.step == 'ask_age':
        try:
            age = int(text.strip())
            if age < 1 or age > 120:
                raise ValueError
        except ValueError:
            return get_msg(lang, 'invalid_input') + "\n" + get_msg(lang, 'ask_age', name=context.get('name', '')), state

        patient, _ = Patient.objects.update_or_create(
            whatsapp_number=state.whatsapp_number,
            defaults={'name': context.get('name', ''), 'age': age, 'language_preference': lang, 'is_registered': True}
        )

        pending_flow = context.get('pending_flow', 'main_menu')
        state.context = {}
        welcome = get_msg(lang, 'registration_complete', name=patient.name)

        if pending_flow == 'booking':
            state.current_flow = 'booking_start'
            state.step = ''
            state.save()
            booking_response, state = start_booking(state)
            if isinstance(booking_response, BotResponse):
                booking_response.text = f"{welcome}\n\n{booking_response.text}"
                return booking_response, state
            return f"{welcome}\n\n{booking_response}", state
        else:
            state.current_flow = 'main_menu'
            state.step = ''
            state.save()
            return _with_menu(lang, welcome), state

    return get_msg(lang, 'error'), state


def handle_main_menu(state, text):
    lang = state.language or 'en'
    lang_name = {'en': 'English', 'hi': 'Hindi', 'mr': 'Marathi'}.get(lang, 'English')
    choice = parse_menu_choice(text, lang_name)

    if choice == '1':
        patient = Patient.objects.filter(whatsapp_number=state.whatsapp_number, is_registered=True).first()
        if not patient:
            state.current_flow = 'registration'
            state.step = 'ask_name'
            state.context = {'pending_flow': 'booking'}
            state.save()
            return get_msg(lang, 'need_registration') + "\n\n" + get_msg(lang, 'ask_name'), state
        return start_booking(state)
    elif choice == '2':
        return start_reschedule(state)
    elif choice == '3':
        return start_cancel(state)
    elif choice == '4':
        return view_appointments(state)
    elif choice == '5':
        state.current_flow = 'enquiry'
        state.step = 'ask_question'
        state.save()
        return get_msg(lang, 'enquiry_prompt'), state
    else:
        return _main_menu_list(lang), state


def start_booking(state):
    lang = state.language or 'en'
    clinic_filter = {'clinic': state.clinic} if state.clinic else {}

    doctors = list(Doctor.objects.filter(
        is_registered=True, slots__is_booked=False, slots__date__gte=date.today(), **clinic_filter
    ).distinct())
    if not doctors:
        doctors = list(Doctor.objects.filter(is_registered=True, **clinic_filter))
    if not doctors:
        return _with_menu(lang, get_msg(lang, 'no_doctors')), state

    state.current_flow = 'booking'

    # Single-doctor clinic → skip the doctor-selection step entirely.
    if len(doctors) == 1:
        doctor = doctors[0]
        state.step = 'select_date'
        state.context = {'doctor_id': doctor.id, 'doctor_name': doctor.name}
        state.save()
        date_response = _date_list(lang, doctor.id, doctor.name)
        if date_response:
            return date_response, state
        return _with_menu(lang, get_msg(lang, 'no_slots', doctor=doctor.name, date='any')), state

    state.step = 'select_doctor'
    state.context = {'doctor_ids': [d.id for d in doctors]}
    state.save()
    return _doctor_list(lang, doctors), state


def handle_booking(state, text):
    lang = state.language or 'en'
    context = state.context or {}

    if state.step == 'select_doctor':
        doctor = _find_doctor(text, context.get('doctor_ids', []))
        if not doctor:
            return get_msg(lang, 'invalid_input'), state

        context['doctor_id'] = doctor.id
        context['doctor_name'] = doctor.name
        state.context = context
        state.step = 'select_date'
        state.save()

        # Show available dates as interactive list
        date_response = _date_list(lang, doctor.id, doctor.name)
        if date_response:
            return date_response, state
        # No dates available at all
        return _with_menu(lang, get_msg(lang, 'no_slots', doctor=doctor.name, date='any')), state

    elif state.step == 'select_date':
        parsed_date = _find_date(text, context.get('doctor_id'))
        if not parsed_date:
            return get_msg(lang, 'invalid_input') + "\n" + get_msg(lang, 'select_date'), state

        slots = AvailableSlot.objects.filter(
            doctor_id=context.get('doctor_id'), date=parsed_date, is_booked=False
        ).order_by('time')
        if not slots.exists():
            return get_msg(lang, 'no_slots', doctor=context.get('doctor_name', ''), date=parsed_date.strftime('%d-%b-%Y')), state

        context['date'] = parsed_date.isoformat()
        context['slot_ids'] = [s.id for s in slots]
        state.context = context
        state.step = 'select_slot'
        state.save()
        return _slot_list(lang, slots, context.get('doctor_name', ''), parsed_date.strftime('%d-%b-%Y')), state

    elif state.step == 'select_slot':
        slot = _find_slot(text, context.get('slot_ids', []))
        if not slot:
            return get_msg(lang, 'invalid_input'), state

        patient = Patient.objects.get(whatsapp_number=state.whatsapp_number)
        doctor = Doctor.objects.get(id=context.get('doctor_id'))
        slot.is_booked = True
        slot.save()
        Appointment.objects.create(patient=patient, doctor=doctor, clinic=doctor.clinic, slot=slot, status='booked')

        state.current_flow = 'main_menu'
        state.step = ''
        state.context = {}
        state.save()

        # Notify doctor instantly
        _notify_doctor('booked', patient.name, doctor,
                       slot.date.strftime('%d-%b-%Y'), slot.time.strftime('%I:%M %p'))

        confirmed = get_msg(lang, 'booking_confirmed', doctor=doctor.name,
                           date=slot.date.strftime('%d-%b-%Y'), time=slot.time.strftime('%I:%M %p'))
        return _with_menu(lang, confirmed), state

    return get_msg(lang, 'error'), state


def start_cancel(state):
    lang = state.language or 'en'
    patient = Patient.objects.filter(whatsapp_number=state.whatsapp_number).first()
    if not patient:
        return _with_menu(lang, get_msg(lang, 'no_appointments')), state

    appointments = Appointment.objects.filter(
        patient=patient, status='booked', slot__date__gte=date.today()
    ).select_related('doctor', 'slot').order_by('slot__date', 'slot__time')
    if not appointments.exists():
        state.current_flow = 'main_menu'
        state.step = ''
        state.save()
        return _with_menu(lang, get_msg(lang, 'no_appointments')), state

    state.current_flow = 'cancel'
    state.step = 'select_appointment'
    state.context = {'appointment_ids': [a.id for a in appointments]}
    state.save()
    return _appointment_list(lang, appointments, 'cancel'), state


def handle_cancel(state, text):
    lang = state.language or 'en'
    context = state.context or {}

    appointment = _find_appointment(text, context.get('appointment_ids', []))
    if not appointment:
        # Check if user wants to go back
        if text.strip() == '0':
            state.current_flow = 'main_menu'
            state.step = ''
            state.context = {}
            state.save()
            return _main_menu_list(lang), state
        return get_msg(lang, 'invalid_input'), state

    appointment.status = 'cancelled'
    appointment.save()
    appointment.slot.is_booked = False
    appointment.slot.save()

    state.current_flow = 'main_menu'
    state.step = ''
    state.context = {}
    state.save()

    # Notify doctor instantly
    patient = Patient.objects.filter(whatsapp_number=state.whatsapp_number).first()
    _notify_doctor('cancelled', patient.name if patient else 'Patient', appointment.doctor,
                   appointment.slot.date.strftime('%d-%b-%Y'),
                   appointment.slot.time.strftime('%I:%M %p'))

    confirmed = get_msg(lang, 'cancel_confirmed', doctor=appointment.doctor.name,
                       date=appointment.slot.date.strftime('%d-%b-%Y'),
                       time=appointment.slot.time.strftime('%I:%M %p'))
    return _with_menu(lang, confirmed), state


def start_reschedule(state):
    lang = state.language or 'en'
    patient = Patient.objects.filter(whatsapp_number=state.whatsapp_number).first()
    if not patient:
        return _with_menu(lang, get_msg(lang, 'no_appointments')), state

    appointments = Appointment.objects.filter(
        patient=patient, status='booked', slot__date__gte=date.today()
    ).select_related('doctor', 'slot').order_by('slot__date', 'slot__time')
    if not appointments.exists():
        state.current_flow = 'main_menu'
        state.step = ''
        state.save()
        return _with_menu(lang, get_msg(lang, 'no_appointments')), state

    state.current_flow = 'reschedule'
    state.step = 'select_appointment'
    state.context = {'appointment_ids': [a.id for a in appointments]}
    state.save()
    return _appointment_list(lang, appointments, 'reschedule'), state


def handle_reschedule(state, text):
    lang = state.language or 'en'
    context = state.context or {}

    if state.step == 'select_appointment':
        appointment = _find_appointment(text, context.get('appointment_ids', []))
        if not appointment:
            if text.strip() == '0':
                state.current_flow = 'main_menu'
                state.step = ''
                state.context = {}
                state.save()
                return _main_menu_list(lang), state
            return get_msg(lang, 'invalid_input'), state

        context['reschedule_appointment_id'] = appointment.id
        context['doctor_id'] = appointment.doctor.id
        context['doctor_name'] = appointment.doctor.name
        state.context = context
        state.step = 'select_date'
        state.save()

        # Show available dates as interactive list
        date_response = _date_list(lang, appointment.doctor.id, appointment.doctor.name)
        if date_response:
            return date_response, state
        return get_msg(lang, 'no_slots', doctor=appointment.doctor.name, date='any'), state

    elif state.step == 'select_date':
        parsed_date = _find_date(text, context.get('doctor_id'))
        if not parsed_date:
            return get_msg(lang, 'invalid_input') + "\n" + get_msg(lang, 'reschedule_select_date'), state

        slots = AvailableSlot.objects.filter(
            doctor_id=context.get('doctor_id'), date=parsed_date, is_booked=False
        ).order_by('time')
        if not slots.exists():
            return get_msg(lang, 'no_slots', doctor=context.get('doctor_name', ''), date=parsed_date.strftime('%d-%b-%Y')), state

        context['date'] = parsed_date.isoformat()
        context['slot_ids'] = [s.id for s in slots]
        state.context = context
        state.step = 'select_slot'
        state.save()
        return _slot_list(lang, slots, context.get('doctor_name', ''), parsed_date.strftime('%d-%b-%Y')), state

    elif state.step == 'select_slot':
        slot = _find_slot(text, context.get('slot_ids', []))
        if not slot:
            return get_msg(lang, 'invalid_input'), state

        old_appt = Appointment.objects.select_related('slot').get(id=context.get('reschedule_appointment_id'))
        old_appt.status = 'cancelled'
        old_appt.save()
        old_appt.slot.is_booked = False
        old_appt.slot.save()

        slot.is_booked = True
        slot.save()

        patient = Patient.objects.get(whatsapp_number=state.whatsapp_number)
        doctor = Doctor.objects.get(id=context.get('doctor_id'))
        Appointment.objects.create(patient=patient, doctor=doctor, clinic=doctor.clinic, slot=slot, status='booked')

        state.current_flow = 'main_menu'
        state.step = ''
        state.context = {}
        state.save()

        # Notify doctor instantly
        _notify_doctor('rescheduled', patient.name, doctor,
                       slot.date.strftime('%d-%b-%Y'), slot.time.strftime('%I:%M %p'))

        confirmed = get_msg(lang, 'reschedule_confirmed', doctor=doctor.name,
                           date=slot.date.strftime('%d-%b-%Y'), time=slot.time.strftime('%I:%M %p'))
        return _with_menu(lang, confirmed), state

    return get_msg(lang, 'error'), state


def view_appointments(state):
    lang = state.language or 'en'
    patient = Patient.objects.filter(whatsapp_number=state.whatsapp_number).first()
    if not patient:
        return _with_menu(lang, get_msg(lang, 'no_appointments')), state

    appointments = Appointment.objects.filter(
        patient=patient, status='booked', slot__date__gte=date.today()
    ).select_related('doctor', 'slot').order_by('slot__date', 'slot__time')
    if not appointments.exists():
        return _with_menu(lang, get_msg(lang, 'no_appointments')), state

    appt_list = "\n".join(
        f"• Dr. {a.doctor.name} — {a.slot.date.strftime('%d-%b-%Y')} at {a.slot.time.strftime('%I:%M %p')}"
        for a in appointments
    )
    return _with_menu(lang, get_msg(lang, 'upcoming_appointments', appointments=appt_list)), state


def handle_enquiry(state, text):
    lang = state.language or 'en'
    state.current_flow = 'main_menu'
    state.step = ''
    state.context = {}
    state.save()
    return _with_menu(lang, get_msg(lang, 'enquiry_default')), state


def parse_date(text: str):
    text = text.strip().lower().replace(',', '')
    today = date.today()
    formats = [
        '%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y', '%d/%m/%y',
        '%d-%B-%Y', '%d-%b-%Y', '%d-%B', '%d-%b',
        '%d %B %Y', '%d %b %Y', '%d %B', '%d %b',
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.date()
        except ValueError:
            continue
    return None
