"""Shared fixtures for the critical-path test suite.

Fixtures:
  • clinic               — A clinic with operating_hours wired
  • doctor               — A registered Doctor at `clinic`
  • patient              — A registered Patient
  • available_slots      — Five open slots for `doctor` tomorrow morning
  • mock_whatsapp_send   — Replaces MockWhatsAppService.send_message with a
                            mock so tests can inspect call_args / call_count
  • signed_payload       — Helper to build Meta-formatted webhook bodies
"""
import json
from datetime import date, time, timedelta

import pytest

from apps.clinic.models import Clinic, Doctor, Patient, AvailableSlot


# ─── Project-wide test settings overrides ────────────────────────────
@pytest.fixture(autouse=True)
def _test_settings(settings):
    """Apply to every test:
      • Use the MOCK WhatsApp service (no real Meta calls anywhere)
      • Empty META_APP_SECRET so signature verification stays in skip mode
      • Celery runs tasks synchronously in-process
    """
    settings.WHATSAPP_SERVICE_CLASS = 'apps.whatsapp.mock_service.MockWhatsAppService'
    settings.META_APP_SECRET = ''
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    return settings


# ─── Model fixtures ──────────────────────────────────────────────────
@pytest.fixture
def clinic(db):
    """Standard test clinic with a full operating-hours JSON.

    `display_phone_number` is what the webhook payload's metadata carries;
    the engine uses it to look up the clinic.
    """
    return Clinic.objects.create(
        name='Test Clinic',
        clinic_code='TEST01',  # generate_monthly_slots task expects this exact code
        display_phone_number='15551234567',
        whatsapp_number='15551234567',
        phone_number_id='test_pnid',
        operating_hours={
            'mon': [['09:00', '13:00'], ['16:00', '20:00']],
            'tue': [['09:00', '13:00'], ['16:00', '20:00']],
            'wed': [['09:00', '13:00'], ['16:00', '20:00']],
            'thu': [['09:00', '13:00'], ['16:00', '20:00']],
            'fri': [['09:00', '13:00'], ['16:00', '20:00']],
            'sat': [['09:00', '13:00']],
            'sun': [],
        },
        slot_minutes=30,
        address='123 Test Street',
    )


@pytest.fixture
def doctor(db, clinic):
    """A registered Doctor — welcomed_at is pre-set so the post_save signal
    skips its welcome-WhatsApp branch (we don't want a Meta call during setup)."""
    from django.utils import timezone
    return Doctor.objects.create(
        clinic=clinic,
        name='Test Doctor',
        # The generate_monthly_slots management command hard-codes this
        # exact number when looking up the demo doctor — test 3 needs it.
        whatsapp_number='917030344210',
        specialty='general',
        is_registered=True,
        welcomed_at=timezone.now(),
    )


@pytest.fixture
def patient(db):
    """A registered Patient with NO language preference set yet.

    State on first message: state.language='' → engine routes to language_select
    (test 2's spec asks for this path explicitly). If a test needs an
    English-already-picked patient, override the fixture or set
    patient.language_preference = 'en' inline.
    """
    return Patient.objects.create(
        whatsapp_number='919222222222',
        name='Test Patient',
        age=30,
        # Explicitly EMPTY language_preference (overrides the model default of
        # 'en') so the engine routes the first message through language_select
        # — that's what Test 2's spec asks for.
        language_preference='',
        is_registered=True,
    )


@pytest.fixture
def available_slots(db, doctor):
    """Five 30-min slots tomorrow, all open."""
    tomorrow = date.today() + timedelta(days=1)
    slots = []
    for hh, mm in [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0)]:
        slots.append(AvailableSlot.objects.create(
            doctor=doctor, date=tomorrow, time=time(hh, mm), is_booked=False,
        ))
    return slots


# ─── Helper to build Meta-format webhook payloads ────────────────────
@pytest.fixture
def signed_payload(clinic):
    """Returns a callable that builds a JSON-encoded Meta payload.

    Usage:
        body_bytes = signed_payload(sender='919...', text='Hi')
    """
    def _build(sender: str, text: str = 'Hi'):
        body = {
            'entry': [{'changes': [{'value': {
                'metadata': {'display_phone_number': clinic.display_phone_number},
                'messages': [{
                    'from': sender,
                    'type': 'text',
                    'text': {'body': text},
                }],
            }}]}],
        }
        return json.dumps(body).encode('utf-8')
    return _build


# ─── Mock for the WhatsApp send call ─────────────────────────────────
@pytest.fixture
def mock_whatsapp_send(mocker):
    """Replace MockWhatsAppService.send_message with a spy returning success."""
    return mocker.patch(
        'apps.whatsapp.mock_service.MockWhatsAppService.send_message',
        return_value={'status': 'success', 'message_id': 'mock_id'},
    )
