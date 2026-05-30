"""Pytest tests for the 5 most critical paths.

Run all:    pytest tests/test_critical_paths.py -v
Run one:    pytest tests/test_critical_paths.py::test_1_webhook_routing -v

External calls (Meta API, Twilio) are mocked via the test settings in
conftest.py (WHATSAPP_SERVICE_CLASS=MockWhatsAppService).
The DB is real — pytest-django creates/manages a test database.
"""
from datetime import date, time, timedelta

import pytest
from django.test import Client

from apps.clinic.models import Appointment, AvailableSlot, Doctor, Patient
from apps.conversations.engine import handle_message
from apps.conversations.models import ConversationState
from apps.notifications.tasks import generate_monthly_slots, send_booking_confirmation


# ────────────────────────────────────────────────────────────────────
# TEST 1 — Webhook routing
# ────────────────────────────────────────────────────────────────────
def test_1_webhook_routing(db, clinic, doctor, signed_payload, mocker):
    """A Meta POST with display_phone_number=clinic.display_phone_number
    routes to handle_message with the matching Clinic object."""

    # Spy on handle_message at the place views.py imports it
    spy = mocker.patch('apps.whatsapp.views.handle_message', return_value='ok')

    body = signed_payload(sender=doctor.whatsapp_number, text='Hi')
    client = Client()
    response = client.post(
        '/api/webhook/whatsapp/',
        data=body,
        content_type='application/json',
    )

    assert response.status_code == 200
    assert spy.called, 'handle_message was not invoked'

    args, kwargs = spy.call_args
    assert args[0] == doctor.whatsapp_number, \
        f'expected phone={doctor.whatsapp_number}, got {args[0]}'
    assert args[1] == 'Hi'
    assert kwargs['clinic'].pk == clinic.pk, \
        f'routed to wrong clinic (got pk={kwargs["clinic"].pk}, want {clinic.pk})'


# ────────────────────────────────────────────────────────────────────
# TEST 2 — New patient booking flow (happy path)
# ────────────────────────────────────────────────────────────────────
def test_2_patient_booking_happy_path(db, clinic, doctor, patient,
                                       available_slots, mocker):
    """End-to-end: patient picks language → menu → book → date → slot.
    Asserts Appointment created, slot.is_booked=True, confirmation task queued."""

    # Spy on the Celery task so we can assert it was scheduled
    task_spy = mocker.patch.object(send_booking_confirmation, 'delay')

    phone = patient.whatsapp_number
    tomorrow = available_slots[0].date

    # 1. "Hi" → language picker
    handle_message(phone, 'Hi', clinic=clinic)
    state = ConversationState.objects.get(whatsapp_number=phone, clinic=clinic)
    assert state.current_flow == 'language_select'

    # 2. "english" → main menu
    handle_message(phone, 'english', clinic=clinic)
    state.refresh_from_db()
    assert state.language == 'en'
    assert state.current_flow == 'main_menu'

    # 3. "1" (book) → patient is already registered, so booking starts
    handle_message(phone, '1', clinic=clinic)
    state.refresh_from_db()
    assert state.current_flow == 'booking', \
        f'expected booking flow, got {state.current_flow!r}'
    # Single-doctor clinic auto-selects → straight to date selection
    assert state.step == 'select_date'

    # 4. Pick tomorrow's date
    handle_message(phone, 'tomorrow', clinic=clinic)
    state.refresh_from_db()
    assert state.step == 'select_slot'
    slot_ids = state.context.get('slot_ids', [])
    assert len(slot_ids) == 5, f'expected 5 slot options, got {len(slot_ids)}'

    # 5. Pick the first slot (the bot's list maps "1" → first slot id)
    handle_message(phone, '1', clinic=clinic)

    # ─── Assertions ───
    appts = Appointment.objects.filter(patient=patient)
    assert appts.count() == 1, f'expected 1 appointment, got {appts.count()}'
    appt = appts.first()
    assert appt.status == 'booked'
    assert appt.slot.date == tomorrow

    appt.slot.refresh_from_db()
    assert appt.slot.is_booked is True, 'slot must be marked booked'

    assert task_spy.called, \
        'send_booking_confirmation.delay(appt.pk) was not dispatched'
    # Confirm the right appointment id was queued
    assert task_spy.call_args[0][0] == appt.pk, \
        f'task dispatched with wrong appt id: {task_spy.call_args}'


# ────────────────────────────────────────────────────────────────────
# TEST 3 — Doctor slot generation (monthly task)
# ────────────────────────────────────────────────────────────────────
def test_3_generate_monthly_slots(db, doctor):
    """Running generate_monthly_slots creates AvailableSlot rows for every
    registered doctor, for dates inside the current/next month, at times
    matching the clinic's operating_hours × slot_minutes."""
    assert AvailableSlot.objects.filter(doctor=doctor).count() == 0

    # Calling .apply() runs the task synchronously in-process
    generate_monthly_slots.apply()

    slots = AvailableSlot.objects.filter(doctor=doctor)
    assert slots.count() > 0, 'no slots generated'

    today = date.today()
    for s in slots:
        assert s.date >= today, f'past-dated slot generated: {s.date}'
        weekday = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][s.date.weekday()]
        shifts = doctor.clinic.operating_hours.get(weekday, [])
        if not shifts:
            pytest.fail(f'slot generated for closed day {weekday}: {s.date}')
        in_a_shift = any(
            time.fromisoformat(open_) <= s.time < time.fromisoformat(close_)
            for open_, close_ in shifts
        )
        assert in_a_shift, \
            f'slot {s.time} on {weekday} is outside operating hours {shifts}'


# ────────────────────────────────────────────────────────────────────
# TEST 4 — Doctor identity resolution
# ────────────────────────────────────────────────────────────────────
def test_4_doctor_identity_resolution(db, clinic, doctor):
    """A message from a registered Doctor's WhatsApp number must result in
    ConversationState.user_type == 'doctor'."""
    handle_message(doctor.whatsapp_number, 'Hi', clinic=clinic)

    state = ConversationState.objects.get(
        whatsapp_number=doctor.whatsapp_number, clinic=clinic,
    )
    assert state.user_type == 'doctor', \
        f'expected user_type=doctor, got {state.user_type!r}'
    assert state.clinic_id == clinic.pk


# ────────────────────────────────────────────────────────────────────
# TEST 5 — Duplicate booking prevention
# ────────────────────────────────────────────────────────────────────
def test_5_booked_slot_not_offered(db, clinic, doctor, patient):
    """An already-booked slot must NEVER appear in the patient's slot list.
    If a slot id IS submitted that isn't in the offered list, the bot
    responds gracefully (no Appointment created)."""
    tomorrow = date.today() + timedelta(days=1)

    open_slot = AvailableSlot.objects.create(
        doctor=doctor, date=tomorrow, time=time(10, 0), is_booked=False,
    )
    booked_slot = AvailableSlot.objects.create(
        doctor=doctor, date=tomorrow, time=time(11, 0), is_booked=True,
    )

    phone = patient.whatsapp_number

    handle_message(phone, 'Hi', clinic=clinic)
    handle_message(phone, 'english', clinic=clinic)
    handle_message(phone, '1', clinic=clinic)
    handle_message(phone, 'tomorrow', clinic=clinic)

    state = ConversationState.objects.get(whatsapp_number=phone, clinic=clinic)
    assert state.step == 'select_slot'

    slot_ids_offered = state.context.get('slot_ids', [])
    assert open_slot.id in slot_ids_offered, 'open slot must be offered'
    assert booked_slot.id not in slot_ids_offered, \
        'already-booked slot must NOT be offered to a different patient'

    # Submitting a non-option must not create an Appointment
    appts_before = Appointment.objects.count()
    handle_message(phone, '99', clinic=clinic)
    assert Appointment.objects.count() == appts_before, \
        'invalid slot selection must NOT create an Appointment'
