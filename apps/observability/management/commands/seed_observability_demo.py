"""Seed realistic RequestLog rows so the admin Logs view has demo data.

Run:    python manage.py seed_observability_demo
Reset:  python manage.py seed_observability_demo --wipe

Each scenario starts a fresh trace, emits its events, then flushes a single
RequestLog row. Result: ~8 rows for ~8 requests, mirroring how production
behaves (1 webhook → 1 row, regardless of how many events fired inside).
"""
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand

from apps.clinic.models import Clinic, Doctor, Patient, AvailableSlot, Appointment
from apps.observability import log
from apps.observability.context import new_trace, set_correlation
from apps.observability.models import RequestLog


def _ensure_fixtures():
    clinic_a, _ = Clinic.objects.get_or_create(
        clinic_code='DEMO_A',
        defaults={'name': 'Sunrise Clinic',
                  'display_phone_number': '917000000001',
                  'phone_number_id': 'demo_pnid_a',
                  'operating_hours': {'mon': [['09:00','13:00']]},
                  'slot_minutes': 30},
    )
    clinic_b, _ = Clinic.objects.get_or_create(
        clinic_code='DEMO_B',
        defaults={'name': 'Orchid Speciality Clinic',
                  'display_phone_number': '917000000002',
                  'phone_number_id': 'demo_pnid_b',
                  'operating_hours': {'mon': [['10:00','14:00'],['16:00','20:00']]},
                  'slot_minutes': 30},
    )
    doc_a, _ = Doctor.objects.get_or_create(
        whatsapp_number='919111111111',
        defaults={'clinic': clinic_a, 'name': 'Anita Sharma',
                  'specialty': 'general', 'is_registered': True},
    )
    doc_b, _ = Doctor.objects.get_or_create(
        whatsapp_number='919222222222',
        defaults={'clinic': clinic_b, 'name': 'Vikram Iyer',
                  'specialty': 'orthopedic', 'is_registered': True},
    )
    patient, _ = Patient.objects.get_or_create(
        whatsapp_number='918333333333',
        defaults={'name': 'Priya Desai', 'age': 28, 'language_preference': 'en',
                  'is_registered': True},
    )
    return clinic_a, clinic_b, doc_a, doc_b, patient


# Each scenario opens a trace, emits a handful of events, then flushes.
# That mirrors how the webhook view behaves in production.

def _patient_booking(clinic, doctor, patient):
    new_trace()
    set_correlation(whatsapp_number=patient.whatsapp_number,
                    clinic_id=clinic.id, user_type='patient',
                    flow='booking', step='select_slot')
    log.event('webhook_received',
              message=f'Inbound from …{patient.whatsapp_number[-4:]} to {clinic.clinic_code}',
              clinic_code=clinic.clinic_code,
              sender_digit10=patient.whatsapp_number[-10:],
              text_preview='1')
    log.event('main_menu_choice', choice='book',
              message='Patient chose Book appointment')
    log.event('booking_started',
              message=f'Auto-selected sole doctor: {doctor.name}',
              doctor=doctor.pk, single_doctor=True)
    log.event('booking_date_selected',
              message=f'Patient picked {date.today().isoformat()} — 4 slots open',
              date=date.today().isoformat(), slot_count=4)
    slot, _ = AvailableSlot.objects.get_or_create(
        doctor=doctor, date=date.today(), time=time(10, 30),
        defaults={'is_booked': True},
    )
    appt, _ = Appointment.objects.get_or_create(
        patient=patient, doctor=doctor, clinic=clinic, slot=slot,
        defaults={'status': 'booked'},
    )
    log.event('appointment_created',
              message=f'Booked: {patient.name} → Dr. {doctor.name} on {slot.date} {slot.time}',
              appointment=appt.pk, patient=patient.pk, doctor=doctor.pk,
              slot=slot.pk, slot_date=slot.date.isoformat(),
              slot_time=slot.time.strftime('%H:%M'))
    log.flush(inbound_text='1', latency_ms=412)


def _doctor_sets_availability(clinic, doctor):
    new_trace()
    set_correlation(whatsapp_number=doctor.whatsapp_number,
                    clinic_id=clinic.id, user_type='doctor',
                    flow='set_availability', step='choose_time_mode')
    log.event('webhook_received',
              message=f'Inbound from …{doctor.whatsapp_number[-4:]} to {clinic.clinic_code}',
              clinic_code=clinic.clinic_code,
              sender_digit10=doctor.whatsapp_number[-10:],
              text_preview='✅ All slots')
    log.event('doctor_menu_choice', choice='set_availability',
              message='Doctor entered Set Availability flow')
    log.event('time_mode_all',
              message='Selected all 8 morning slots',
              session='morning', slot_count=8)
    log.event('slots_saved',
              message=f'7 new slots created for Dr. {doctor.name}',
              doctor=doctor.pk, clinic_code=clinic.clinic_code,
              dates=1, times=8, created=7, existed=1, out_of_hours=0)
    log.flush(inbound_text='✅ All slots', latency_ms=623)


def _time_match_failed(clinic, doctor):
    new_trace()
    set_correlation(whatsapp_number=doctor.whatsapp_number,
                    clinic_id=clinic.id, user_type='doctor',
                    flow='set_availability', step='select_slots')
    log.event('webhook_received',
              clinic_code=clinic.clinic_code,
              sender_digit10=doctor.whatsapp_number[-10:],
              text_preview='9 AM',
              message='Inbound from doctor with custom time text')
    log.warn('time_match_failed',
             message='Doctor input did not match any clinic-hour slot',
             input='9 AM', cleaned='9 AM', session='morning',
             ref_date=date.today().isoformat(),
             candidate_count=8,
             candidates_sample=['09:00', '09:30', '10:00', '10:30', '11:00'],
             clinic_code=clinic.clinic_code)
    log.flush(inbound_text='9 AM', latency_ms=287)


def _doctor_lookup_miss(clinic):
    new_trace()
    bogus_wa = '917030344210'
    set_correlation(whatsapp_number=bogus_wa, clinic_id=clinic.id,
                    user_type='doctor', flow='doctor_menu')
    log.event('webhook_received',
              clinic_code=clinic.clinic_code,
              sender_digit10=bogus_wa[-10:], text_preview='3')
    log.event('doctor_menu_choice', choice='upcoming_bookings',
              message="Doctor opened Upcoming Bookings")
    log.error('doctor_lookup_miss',
              message='Doctor row missing for cached doctor-state sender; resetting state',
              wa_state=bogus_wa, digit10=bogus_wa[-10:],
              near_match='7030344210', near_registered=False)
    log.flush(inbound_text='3', latency_ms=193)


def _same_day_blocked(clinic, doctor, patient):
    new_trace()
    set_correlation(whatsapp_number=patient.whatsapp_number, clinic_id=clinic.id,
                    user_type='patient', flow='booking', step='select_date')
    log.event('webhook_received',
              clinic_code=clinic.clinic_code,
              sender_digit10=patient.whatsapp_number[-10:],
              text_preview='today',
              message='Inbound from patient choosing a date')
    log.event('booking_blocked_same_day',
              message='Patient already has an appointment that day',
              patient=patient.pk, existing_appointment=1,
              existing_doctor=doctor.name,
              date=date.today().isoformat())
    log.flush(inbound_text='today', latency_ms=156)


def _cancellation(clinic, doctor, patient):
    new_trace()
    set_correlation(whatsapp_number=patient.whatsapp_number, clinic_id=clinic.id,
                    user_type='patient', flow='cancel', step='select_appointment')
    log.event('webhook_received',
              clinic_code=clinic.clinic_code,
              sender_digit10=patient.whatsapp_number[-10:],
              text_preview='3')
    log.event('main_menu_choice', choice='cancel',
              message='Patient chose Cancel')
    log.event('appointment_cancelled',
              message=f'Cancelled: {doctor.name} on {date.today() + timedelta(days=1)}',
              appointment=2, doctor=doctor.pk,
              slot_date=(date.today() + timedelta(days=1)).isoformat(),
              slot_time='15:00')
    log.flush(inbound_text='3', latency_ms=311)


def _unknown_clinic():
    new_trace()
    stranger_wa = '919876500000'
    set_correlation(whatsapp_number=stranger_wa)
    log.warn('webhook_unmatched_clinic',
             message='No Clinic registered for this display_phone_number',
             display_number='15551111111', sender_digit10=stranger_wa[-10:])
    log.flush(inbound_text='hi', latency_ms=42)


def _meta_131030(clinic, doctor):
    new_trace()
    set_correlation(whatsapp_number=doctor.whatsapp_number, clinic_id=clinic.id,
                    user_type='system')
    log.event('webhook_received', clinic_code=clinic.clinic_code,
              sender_digit10=doctor.whatsapp_number[-10:],
              text_preview='hi')
    log.error('send_response_failed',
              message='Meta rejected the send',
              exc_type='WhatsAppSendError',
              exc_message='Meta 131030: Recipient phone number not in allowed list',
              recipient_digit10=doctor.whatsapp_number[-10:],
              clinic_code=clinic.clinic_code, meta_code=131030,
              latency_ms=412)
    log.flush(inbound_text='hi', latency_ms=487)


class Command(BaseCommand):
    help = 'Seed realistic RequestLog rows for the admin Logs view.'

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true',
                            help='Delete existing RequestLog rows first')

    def handle(self, *args, **opts):
        if opts['wipe']:
            n = RequestLog.objects.all().count()
            RequestLog.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'  Wiped {n} existing rows'))

        clinic_a, clinic_b, doc_a, doc_b, patient = _ensure_fixtures()

        scenarios = [
            ('Patient booking — happy path',         _patient_booking,         (clinic_a, doc_a, patient)),
            ('Doctor sets availability',             _doctor_sets_availability,(clinic_a, doc_a)),
            ('Doctor input rejected (time)',         _time_match_failed,       (clinic_a, doc_a)),
            ('Doctor record missing — cached',       _doctor_lookup_miss,      (clinic_b,)),
            ('Same-day booking blocked',             _same_day_blocked,        (clinic_a, doc_a, patient)),
            ('Appointment cancellation',             _cancellation,            (clinic_a, doc_a, patient)),
            ('Webhook hit by unknown clinic',        _unknown_clinic,          ()),
            ('WhatsApp send failure (Meta 131030)',  _meta_131030,             (clinic_b, doc_b)),
        ]

        for label, fn, args in scenarios:
            fn(*args)
            self.stdout.write(self.style.SUCCESS(f'  ✓ {label}'))

        total = RequestLog.objects.count()
        warnings = RequestLog.objects.filter(level='warn').count()
        errors = RequestLog.objects.filter(level='error').count()
        events_total = sum(RequestLog.objects.values_list('event_count', flat=True))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'  {total} request rows · {events_total} events buffered into them · '
            f'{warnings} warnings · {errors} errors'
        ))
        self.stdout.write('')
        self.stdout.write('  Browse them at:')
        self.stdout.write(self.style.WARNING(
            '  http://127.0.0.1:8001/admin/observability/requestlog/'
        ))
