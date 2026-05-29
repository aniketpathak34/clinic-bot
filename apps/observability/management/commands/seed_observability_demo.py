"""Seed realistic observability events so the admin Logs view has data to show.

Run:    python manage.py seed_observability_demo
Reset:  python manage.py seed_observability_demo --wipe

Eight scenarios are generated, each with its own trace_id, covering the
range of event types and levels you'll see in production:

  1. Patient booking — happy path (10 events, all INFO)
  2. Doctor sets availability — bulk save (8 events)
  3. Doctor input rejected — out-of-hours time (4 events, includes WARN)
  4. Doctor record missing — cached state (4 events, includes ERROR)
  5. Same-day booking blocked (5 events, ends with friendly redirect)
  6. Appointment cancellation (5 events)
  7. Webhook with unknown clinic (2 events, includes WARN)
  8. WhatsApp send failure — Meta 131030 (4 events, includes ERROR)
"""
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand

from apps.clinic.models import Clinic, Doctor, Patient, AvailableSlot, Appointment
from apps.observability import log
from apps.observability.context import new_trace, set_correlation
from apps.observability.models import LogEvent


def _ensure_fixtures():
    """Make sure the clinics/doctors/patients referenced by the scenarios exist."""
    clinic_a, _ = Clinic.objects.get_or_create(
        clinic_code='DEMO_A',
        defaults={'name': 'Sunrise Clinic',
                  'display_phone_number': '917000000001',
                  'phone_number_id': 'demo_pnid_a',
                  'operating_hours': {'mon': [['09:00','13:00']], 'tue': [['09:00','13:00']]},
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


def _scenario_1_patient_booking(clinic, doctor, patient):
    """Healthy patient booking — webhook → identity → menu → book."""
    new_trace()
    set_correlation(whatsapp_number=patient.whatsapp_number,
                    clinic_id=clinic.id, user_type='patient')

    log.event('webhook_received',
              message=f'Inbound from …{patient.whatsapp_number[-4:]} to {clinic.clinic_code}',
              clinic_code=clinic.clinic_code,
              sender_digit10=patient.whatsapp_number[-10:],
              text_preview='1')
    log.event('identity_resolved',
              message=f'Identified as patient on {clinic.clinic_code}',
              resolved_type='patient', matched_by='inbound_clinic')
    set_correlation(flow='main_menu', step='')
    log.event('route_dispatched', message='Dispatching to patient flow', target='patient')
    log.event('main_menu_choice', choice='book', message='Patient chose Book appointment')
    set_correlation(flow='booking', step='select_date')
    log.event('booking_started',
              message=f'Auto-selected sole doctor: {doctor.name}',
              doctor=doctor.pk, doctor_name=doctor.name, single_doctor=True)
    log.event('booking_date_selected',
              message=f'Patient picked {date.today().isoformat()} — 4 slots open',
              date=date.today().isoformat(), slot_count=4)
    set_correlation(step='select_slot')
    # Create a fake appointment row so the FK is real
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


def _scenario_2_doctor_sets_availability(clinic, doctor):
    """Doctor walks through full Set Availability flow."""
    new_trace()
    set_correlation(whatsapp_number=doctor.whatsapp_number,
                    clinic_id=clinic.id, user_type='doctor')

    log.event('webhook_received',
              message=f'Inbound from …{doctor.whatsapp_number[-4:]} to {clinic.clinic_code}',
              clinic_code=clinic.clinic_code,
              sender_digit10=doctor.whatsapp_number[-10:],
              text_preview='Hi')
    log.event('identity_resolved',
              message=f'Identified as doctor {doctor.name}',
              resolved_type='doctor', matched_by='exact_phone',
              doctor_id=doctor.pk)
    set_correlation(flow='doctor_menu')
    log.event('route_dispatched', target='doctor')
    set_correlation(flow='set_availability', step='choose_date_mode')
    log.event('doctor_menu_choice', choice='set_availability',
              message='Doctor entered Set Availability flow')
    log.event('handle_set_availability',
              message='Inbound to set_availability flow at step=choose_date_mode',
              text='📅 Next 7 days', clinic_code=clinic.clinic_code)
    set_correlation(step='choose_time_mode')
    log.event('step_transition', message='Doctor chose custom time picker',
              to='select_slots', via='custom_button')
    set_correlation(step='choose_time_mode')
    log.event('time_mode_all', message='Selected all 8 morning slots',
              session='morning', slot_count=8)
    log.event('slots_saved',
              message=f'7 new slots created for Dr. {doctor.name}',
              doctor=doctor.pk, clinic_code=clinic.clinic_code,
              dates=1, times=8, created=7, existed=1, out_of_hours=0)


def _scenario_3_time_match_failed(clinic, doctor):
    """Doctor types '9 AM' but options are formatted '09:00' — soft reject."""
    new_trace()
    set_correlation(whatsapp_number=doctor.whatsapp_number, clinic_id=clinic.id,
                    user_type='doctor', flow='set_availability', step='select_slots')

    log.event('webhook_received',
              clinic_code=clinic.clinic_code,
              sender_digit10=doctor.whatsapp_number[-10:],
              text_preview='9 AM')
    log.event('route_dispatched', target='doctor')
    log.event('handle_set_availability', text='9 AM',
              clinic_code=clinic.clinic_code,
              message='Inbound to set_availability flow at step=select_slots')
    log.warn('time_match_failed',
             message='Doctor input did not match any clinic-hour slot',
             input='9 AM', cleaned='9 AM', session='morning',
             ref_date=date.today().isoformat(),
             candidate_count=8,
             candidates_sample=['09:00', '09:30', '10:00', '10:30', '11:00'],
             clinic_code=clinic.clinic_code)


def _scenario_4_doctor_lookup_miss(clinic):
    """Cached state says doctor, but Doctor row missing — full ERROR + self-heal."""
    new_trace()
    bogus_wa = '917030344210'  # the exact bug we hit
    set_correlation(whatsapp_number=bogus_wa, clinic_id=clinic.id,
                    user_type='doctor', flow='doctor_menu')

    log.event('webhook_received', clinic_code=clinic.clinic_code,
              sender_digit10=bogus_wa[-10:], text_preview='3')
    log.event('route_dispatched', target='doctor',
              message='Cached state says doctor, dispatching')
    log.event('doctor_menu_choice', choice='upcoming_bookings',
              message="Doctor opened Upcoming Bookings")
    log.error('doctor_lookup_miss',
              message='Doctor row missing for cached doctor-state sender; resetting state',
              wa_state=bogus_wa, digit10=bogus_wa[-10:],
              near_match='7030344210',
              near_registered=False)


def _scenario_5_same_day_booking_blocked(clinic, doctor, patient):
    """Patient tries to book a 2nd appt same day — bot redirects."""
    new_trace()
    set_correlation(whatsapp_number=patient.whatsapp_number, clinic_id=clinic.id,
                    user_type='patient', flow='booking', step='select_date')

    log.event('webhook_received', clinic_code=clinic.clinic_code,
              sender_digit10=patient.whatsapp_number[-10:],
              text_preview='today')
    log.event('route_dispatched', target='patient')
    log.event('booking_blocked_same_day',
              message='Patient already has an appointment that day',
              patient=patient.pk,
              existing_appointment=1,
              existing_doctor=doctor.name,
              date=date.today().isoformat())


def _scenario_6_appointment_cancellation(clinic, doctor, patient):
    """Patient cancels an existing appointment."""
    new_trace()
    set_correlation(whatsapp_number=patient.whatsapp_number, clinic_id=clinic.id,
                    user_type='patient', flow='cancel', step='select_appointment')

    log.event('webhook_received', clinic_code=clinic.clinic_code,
              sender_digit10=patient.whatsapp_number[-10:],
              text_preview='3')
    log.event('main_menu_choice', choice='cancel',
              message='Patient chose Cancel')
    log.event('route_dispatched', target='patient')
    log.event('appointment_cancelled',
              message=f'Cancelled: {doctor.name} on {date.today() + timedelta(days=1)}',
              appointment=2,
              doctor=doctor.pk,
              slot_date=(date.today() + timedelta(days=1)).isoformat(),
              slot_time='15:00')


def _scenario_7_unknown_clinic_webhook(stranger_wa='919876500000'):
    """Webhook hit by someone messaging a number we don't have a Clinic for."""
    new_trace()
    set_correlation(whatsapp_number=stranger_wa)

    log.warn('webhook_unmatched_clinic',
             message='No Clinic registered for this display_phone_number',
             display_number='15551111111',
             sender_digit10=stranger_wa[-10:])


def _scenario_8_meta_131030_send_failure(clinic, doctor):
    """The 131030 Meta error — actionable warning, not noisy error."""
    new_trace()
    set_correlation(whatsapp_number=doctor.whatsapp_number, clinic_id=clinic.id,
                    user_type='system')

    log.event('webhook_received', clinic_code=clinic.clinic_code,
              sender_digit10=doctor.whatsapp_number[-10:],
              text_preview='hi')
    log.event('identity_resolved', resolved_type='doctor',
              matched_by='exact_phone', doctor_id=doctor.pk)
    # send_response_failed span (would normally fire from the span context mgr)
    log.error('send_response_failed', latency_ms=412,
              message='Meta rejected the send',
              exc_type='WhatsAppSendError',
              exc_message="Meta 131030: Recipient phone number not in allowed list",
              recipient_digit10=doctor.whatsapp_number[-10:],
              clinic_code=clinic.clinic_code,
              meta_code=131030)


class Command(BaseCommand):
    help = 'Seed realistic LogEvent rows so the admin Logs view has demo data.'

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true',
                            help='Delete all existing LogEvent rows before seeding')

    def handle(self, *args, **opts):
        if opts['wipe']:
            n = LogEvent.objects.all().count()
            LogEvent.objects.all().delete()
            self.stdout.write(self.style.WARNING(f'  Wiped {n} existing LogEvent rows'))

        clinic_a, clinic_b, doc_a, doc_b, patient = _ensure_fixtures()

        scenarios = [
            ('Patient booking — happy path',         _scenario_1_patient_booking,         (clinic_a, doc_a, patient)),
            ('Doctor sets availability',             _scenario_2_doctor_sets_availability,(clinic_a, doc_a)),
            ('Doctor input rejected (time)',         _scenario_3_time_match_failed,       (clinic_a, doc_a)),
            ('Doctor record missing — cached',       _scenario_4_doctor_lookup_miss,      (clinic_b,)),
            ('Same-day booking blocked',             _scenario_5_same_day_booking_blocked,(clinic_a, doc_a, patient)),
            ('Appointment cancellation',             _scenario_6_appointment_cancellation,(clinic_a, doc_a, patient)),
            ('Webhook hit by unknown clinic',        _scenario_7_unknown_clinic_webhook,  ()),
            ('WhatsApp send failure (Meta 131030)',  _scenario_8_meta_131030_send_failure,(clinic_b, doc_b)),
        ]

        for label, fn, args in scenarios:
            before = LogEvent.objects.count()
            fn(*args)
            after = LogEvent.objects.count()
            self.stdout.write(self.style.SUCCESS(
                f'  ✓ {label:<40} +{after - before} events'
            ))

        total = LogEvent.objects.count()
        warnings = LogEvent.objects.filter(level='warn').count()
        errors = LogEvent.objects.filter(level='error').count()
        traces = LogEvent.objects.values('trace_id').distinct().count()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'  Total: {total} events · {traces} traces · '
            f'{warnings} warnings · {errors} errors'
        ))
        self.stdout.write('')
        self.stdout.write('  Browse them at:')
        self.stdout.write(self.style.WARNING(
            '  http://127.0.0.1:8001/admin/observability/logevent/'
        ))
