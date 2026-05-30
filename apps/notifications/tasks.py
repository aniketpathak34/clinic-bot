"""Celery tasks for appointment notifications and automated calls."""
import logging
import zoneinfo
from datetime import date, datetime, timedelta
from functools import wraps

from celery import shared_task
from django.utils import timezone

from apps.clinic.models import Appointment
from apps.observability import log
from apps.observability.context import new_trace, set_correlation
from apps.whatsapp.utils import get_whatsapp_service
from bot_locale.messages import get_msg
from .call_service import get_call_service
from .models import CallLog

logger = logging.getLogger(__name__)

IST = zoneinfo.ZoneInfo('Asia/Kolkata')


def _task_trace(task_name: str):
    """Wrap a @shared_task body so it:
      • Opens a fresh trace at entry → events go into one buffer
      • Calls log.flush(request_kind='task') at exit → ONE RequestLog row
      • Catches + logs unhandled exceptions, then re-raises so Celery retries
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            import time as _t
            new_trace()
            started = _t.monotonic()
            try:
                result = fn(*args, **kwargs)
                log.flush(request_kind='task',
                          inbound_text=f'task:{task_name}',
                          latency_ms=int((_t.monotonic() - started) * 1000))
                return result
            except Exception as e:
                log.error(f'task_{task_name}_crashed', exc=e,
                          message=f'Celery task {task_name} raised')
                log.flush(request_kind='task',
                          inbound_text=f'task:{task_name}',
                          latency_ms=int((_t.monotonic() - started) * 1000))
                raise
        return wrapper
    return decorator


@shared_task
@_task_trace('send_booking_confirmation')
def send_booking_confirmation(appointment_id):
    """Send booking confirmation to patient + notification to doctor."""
    try:
        appointment = Appointment.objects.select_related(
            'patient', 'doctor', 'clinic', 'slot'
        ).get(id=appointment_id)
    except Appointment.DoesNotExist:
        log.error('appointment_not_found',
                  message=f'Appointment {appointment_id} not found',
                  appointment_id=appointment_id)
        return

    set_correlation(clinic_id=appointment.clinic_id,
                    whatsapp_number=appointment.patient.whatsapp_number)
    service = get_whatsapp_service(clinic=appointment.clinic)
    lang = appointment.patient.language_preference or 'en'

    # Confirm to patient
    patient_msg = get_msg(lang, 'booking_confirmed',
                         doctor=appointment.doctor.name,
                         date=appointment.slot.date.strftime('%d-%b-%Y'),
                         time=appointment.slot.time.strftime('%I:%M %p'))
    service.send_message(appointment.patient.whatsapp_number, patient_msg)

    # Notify doctor
    doctor_msg = get_msg('en', 'doctor_new_booking_notification',
                        patient=appointment.patient.name,
                        date=appointment.slot.date.strftime('%d-%b-%Y'),
                        time=appointment.slot.time.strftime('%I:%M %p'))
    service.send_message(appointment.doctor.whatsapp_number, doctor_msg)

    log.event('booking_confirmation_sent',
              message='Confirmation + doctor notification sent',
              appointment_id=appointment_id,
              doctor_id=appointment.doctor_id,
              patient_id=appointment.patient_id,
              clinic_code=appointment.clinic.clinic_code)


@shared_task
@_task_trace('send_day_before_reminders')
def send_day_before_reminders():
    """Send WhatsApp reminders for tomorrow's appointments. Runs daily at 6 PM IST."""
    tomorrow = date.today() + timedelta(days=1)
    appointments = Appointment.objects.filter(
        status='booked',
        slot__date=tomorrow,
    ).select_related('patient', 'doctor', 'slot', 'clinic')

    count = 0

    for appointment in appointments:
        try:
            if not appointment.clinic.subscription.allows('day_before_reminders'):
                continue
        except Exception:
            pass  # no subscription row = allow through

        service = get_whatsapp_service(clinic=appointment.clinic)
        lang = appointment.patient.language_preference or 'en'
        reminder_msg = get_msg(lang, 'booking_confirmed',
                              doctor=appointment.doctor.name,
                              date=appointment.slot.date.strftime('%d-%b-%Y'),
                              time=appointment.slot.time.strftime('%I:%M %p'))
        # Prepend reminder text
        if lang == 'hi':
            reminder_msg = "⏰ कल की अपॉइंटमेंट का रिमाइंडर:\n\n" + reminder_msg
        elif lang == 'mr':
            reminder_msg = "⏰ उद्याच्या अपॉइंटमेंटची आठवण:\n\n" + reminder_msg
        else:
            reminder_msg = "⏰ Reminder for tomorrow's appointment:\n\n" + reminder_msg

        service.send_message(appointment.patient.whatsapp_number, reminder_msg)
        count += 1

    log.event('day_before_reminders_sent',
              message=f'Sent {count} reminders for {tomorrow}',
              date=tomorrow.isoformat(), count=count)
    return count


@shared_task
@_task_trace('make_confirmation_calls')
def make_confirmation_calls():
    """Make automated calls to confirm tomorrow's appointments.
    Runs daily at 10 AM IST (morning of previous day).
    Calls patients and asks them to press 1 (confirm) or 2 (cancel).
    """
    tomorrow = date.today() + timedelta(days=1)
    appointments = Appointment.objects.filter(
        status='booked',
        slot__date=tomorrow,
    ).select_related('patient', 'doctor', 'slot')

    call_service = get_call_service()
    count = 0

    for appointment in appointments:
        # Skip if already called and confirmed
        existing_call = CallLog.objects.filter(
            appointment=appointment,
            status='confirmed'
        ).exists()
        if existing_call:
            continue

        # Check how many attempts already made
        attempt_count = CallLog.objects.filter(appointment=appointment).count()
        if attempt_count >= 3:  # Max 3 call attempts
            log.warn('call_max_attempts',
                     message=f'3 attempts reached for appt {appointment.id}; skipping',
                     appointment_id=appointment.id)
            continue

        lang = appointment.patient.language_preference or 'en'

        result = call_service.make_confirmation_call(
            to=appointment.patient.whatsapp_number,
            patient_name=appointment.patient.name,
            doctor_name=appointment.doctor.name,
            appointment_date=appointment.slot.date.strftime('%d-%b-%Y'),
            appointment_time=appointment.slot.time.strftime('%I:%M %p'),
            appointment_id=appointment.id,
            language=lang,
        )

        # Log the call
        CallLog.objects.create(
            appointment=appointment,
            phone_number=appointment.patient.whatsapp_number,
            call_id=result.get('call_id', ''),
            status='initiated',
            attempt_number=attempt_count + 1,
        )

        count += 1

    log.event('confirmation_calls_initiated',
              message=f'{count} calls initiated for {tomorrow}',
              date=tomorrow.isoformat(), count=count)
    return count


@shared_task
@_task_trace('handle_call_response')
def handle_call_response(appointment_id, patient_response):
    """Handle patient's response from the automated call.
    patient_response: '1' = confirm, '2' = cancel
    """
    try:
        appointment = Appointment.objects.select_related(
            'patient', 'doctor', 'slot', 'clinic'
        ).get(id=appointment_id)
    except Appointment.DoesNotExist:
        log.error('appointment_not_found',
                  message=f'Appointment {appointment_id} not found for call response',
                  appointment_id=appointment_id)
        return

    set_correlation(clinic_id=appointment.clinic_id,
                    whatsapp_number=appointment.patient.whatsapp_number)
    service = get_whatsapp_service(clinic=appointment.clinic)
    lang = appointment.patient.language_preference or 'en'

    if patient_response == '1':
        # Patient confirmed
        CallLog.objects.filter(
            appointment=appointment, status='initiated'
        ).update(status='confirmed')

        # Send WhatsApp confirmation
        msg = get_msg(lang, 'call_confirmed',
                     doctor=appointment.doctor.name,
                     date=appointment.slot.date.strftime('%d-%b-%Y'),
                     time=appointment.slot.time.strftime('%I:%M %p'))
        service.send_message(appointment.patient.whatsapp_number, msg)
        log.event('appointment_confirmed_via_call',
                  message=f'Patient pressed 1 for appt {appointment_id}',
                  appointment_id=appointment_id,
                  doctor_id=appointment.doctor_id)

    elif patient_response == '2':
        # Patient wants to cancel
        appointment.status = 'cancelled'
        appointment.save()
        appointment.slot.is_booked = False
        appointment.slot.save()

        CallLog.objects.filter(
            appointment=appointment, status='initiated'
        ).update(status='cancelled')

        # Notify patient via WhatsApp
        msg = get_msg(lang, 'cancel_confirmed',
                     doctor=appointment.doctor.name,
                     date=appointment.slot.date.strftime('%d-%b-%Y'),
                     time=appointment.slot.time.strftime('%I:%M %p'))
        service.send_message(appointment.patient.whatsapp_number, msg)

        # Notify doctor
        doctor_msg = get_msg('en', 'doctor_cancel_notification',
                            patient=appointment.patient.name,
                            date=appointment.slot.date.strftime('%d-%b-%Y'),
                            time=appointment.slot.time.strftime('%I:%M %p'))
        service.send_message(appointment.doctor.whatsapp_number, doctor_msg)

        log.event('appointment_cancelled_via_call',
                  message=f'Patient pressed 2 for appt {appointment_id}',
                  appointment_id=appointment_id,
                  doctor_id=appointment.doctor_id)


@shared_task
@_task_trace('retry_unanswered_calls')
def retry_unanswered_calls():
    """Retry calls that were not answered. Runs at 2 PM IST."""
    tomorrow = date.today() + timedelta(days=1)

    # Find appointments with initiated but not confirmed/cancelled calls
    unanswered = CallLog.objects.filter(
        appointment__status='booked',
        appointment__slot__date=tomorrow,
        status='initiated',
        attempt_number__lt=3,
    ).select_related('appointment__patient', 'appointment__doctor', 'appointment__slot')

    call_service = get_call_service()
    count = 0

    for call_log in unanswered:
        # Mark previous attempt as no_answer
        call_log.status = 'no_answer'
        call_log.save()

        appointment = call_log.appointment
        lang = appointment.patient.language_preference or 'en'

        result = call_service.make_confirmation_call(
            to=appointment.patient.whatsapp_number,
            patient_name=appointment.patient.name,
            doctor_name=appointment.doctor.name,
            appointment_date=appointment.slot.date.strftime('%d-%b-%Y'),
            appointment_time=appointment.slot.time.strftime('%I:%M %p'),
            appointment_id=appointment.id,
            language=lang,
        )

        CallLog.objects.create(
            appointment=appointment,
            phone_number=appointment.patient.whatsapp_number,
            call_id=result.get('call_id', ''),
            status='initiated',
            attempt_number=call_log.attempt_number + 1,
        )

        count += 1

    log.event('unanswered_calls_retried',
              message=f'Retried {count} calls', count=count)
    return count


@shared_task
@_task_trace('send_hour_before_reminders')
def send_hour_before_reminders():
    """Notify patients whose appointment starts in ~1 hour.

    Designed to run every 5 minutes via Celery Beat. Uses a 55–70 minute
    window so every appointment gets exactly one reminder around T-60min;
    idempotency is enforced by Appointment.hour_before_reminded_at.
    """
    now_ist = timezone.now().astimezone(IST)
    window_start = now_ist + timedelta(minutes=55)
    window_end = now_ist + timedelta(minutes=70)

    # Query candidates by date only (covers the possible range, including midnight crossover)
    candidate_dates = {window_start.date(), window_end.date()}
    candidates = Appointment.objects.filter(
        status='booked',
        hour_before_reminded_at__isnull=True,
        slot__date__in=candidate_dates,
    ).select_related('patient', 'doctor', 'slot', 'clinic')

    count = 0
    for appt in candidates:
        # Reconstruct the appointment's IST start time
        appt_dt = datetime.combine(appt.slot.date, appt.slot.time, tzinfo=IST)
        if not (window_start <= appt_dt <= window_end):
            continue

        try:
            if not appt.clinic.subscription.allows('hour_before_reminders'):
                continue
        except Exception:
            pass  # no subscription row = allow through

        lang = appt.patient.language_preference or 'en'
        msg = get_msg(
            lang, 'reminder_hour_before',
            doctor=appt.doctor.name,
            clinic_name=appt.clinic.name,
            date=appt.slot.date.strftime('%d-%b-%Y'),
            time=appt.slot.time.strftime('%I:%M %p'),
            address=appt.clinic.address or '—',
        )

        try:
            service = get_whatsapp_service(clinic=appt.clinic)
            result = service.send_message(appt.patient.whatsapp_number, msg)
            if result.get('status') == 'error':
                log.error('hour_before_send_failed',
                          message=f'Meta send failed for appt {appt.id}',
                          appointment_id=appt.id,
                          meta_result=str(result)[:200])
                continue
        except Exception as e:
            log.error('hour_before_send_crashed', exc=e,
                      message=f'Send crashed for appt {appt.id}',
                      appointment_id=appt.id)
            continue

        Appointment.objects.filter(pk=appt.pk, hour_before_reminded_at__isnull=True).update(
            hour_before_reminded_at=timezone.now()
        )
        log.event('hour_before_reminder_sent',
                  message=f'Reminder sent for appt {appt.id}',
                  appointment_id=appt.id,
                  slot_date=appt.slot.date.isoformat(),
                  slot_time=appt.slot.time.strftime('%H:%M'))
        count += 1

    log.event('hour_before_batch_done',
              message=f'Batch done — {count} reminders',
              count=count,
              window_start=window_start.time().isoformat(),
              window_end=window_end.time().isoformat())
    return count


@shared_task
@_task_trace('fetch_daily_leads')
def fetch_daily_leads(top_n: int = 20):
    """Pull fresh clinic leads from Google Places API and save the top N as Lead rows.

    Calls the seed_leads management command — keeps the lead-gen logic in one place.
    Default 20 leads/day with strict score threshold for high conversion quality.
    """
    from django.core.management import call_command
    try:
        call_command('seed_leads', top=top_n)
        log.event('leads_fetched',
                  message=f'fetch_daily_leads ran with top={top_n}',
                  top_n=top_n)
    except Exception as e:
        log.error('lead_fetch_failed', exc=e, top_n=top_n,
                  message='Lead-gen command crashed')
        raise


@shared_task
@_task_trace('check_subscription_status')
def check_subscription_status():
    """Daily 2 AM IST: flip subscription statuses per grace policy.

    pilot + pilot_ends_at < today           → past_due
    past_due + current_period_end < today-7d → suspended
    suspended + current_period_end < today-30d → cancelled
    Also logs which clinics renew in the next 3 days.
    """
    from apps.subscriptions.models import Subscription

    today = timezone.now().astimezone(IST).date()

    pilot_expired = Subscription.objects.filter(
        status='pilot',
        pilot_ends_at__lt=today,
    ).update(status='past_due', current_period_end=today)

    grace_over = Subscription.objects.filter(
        status='past_due',
        current_period_end__lt=today - timedelta(days=7),
    ).update(status='suspended')

    long_suspended = Subscription.objects.filter(
        status='suspended',
        current_period_end__lt=today - timedelta(days=30),
    ).update(status='cancelled')

    renewing_soon = list(
        Subscription.objects
        .filter(
            status='active',
            current_period_end__lte=today + timedelta(days=3),
            current_period_end__gte=today,
        )
        .select_related('clinic')
        .values_list('clinic__clinic_code', 'current_period_end')
    )

    log.event(
        'subscription_status_check_ran',
        message=(f'pilot→past_due={pilot_expired} '
                 f'past_due→suspended={grace_over} '
                 f'suspended→cancelled={long_suspended} '
                 f'renewing_in_3d={len(renewing_soon)}'),
        flipped_past_due=pilot_expired,
        flipped_suspended=grace_over,
        flipped_cancelled=long_suspended,
        renewing_soon=[f'{code} due {d:%d %b}' for code, d in renewing_soon],
    )


@shared_task
@_task_trace('generate_monthly_slots')
def generate_monthly_slots():
    """Fill AvailableSlot rows for the demo doctor for the entire current month.

    Triggered by the monthly GitHub Actions cron (1st of each month). Idempotent
    — get_or_create on (doctor, date, time) so re-runs are no-ops.
    """
    from io import StringIO
    from django.core.management import call_command
    out = StringIO()
    try:
        call_command('generate_monthly_slots', stdout=out, stderr=out)
        result = (out.getvalue() or '').strip().splitlines()
        last = result[-1] if result else ''
        log.event('monthly_slots_generated',
                  message=last or 'monthly-slots ran',
                  summary_line=last)
        return last
    except Exception as e:
        log.error('monthly_slots_failed', exc=e,
                  message='monthly-slots task crashed')
        raise
