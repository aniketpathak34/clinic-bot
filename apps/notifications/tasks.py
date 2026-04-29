"""Celery tasks for appointment notifications and automated calls."""
import logging
import zoneinfo
from datetime import date, datetime, timedelta

from celery import shared_task
from django.utils import timezone

from apps.clinic.models import Appointment
from apps.whatsapp.utils import get_whatsapp_service
from bot_locale.messages import get_msg
from .call_service import get_call_service
from .models import CallLog

logger = logging.getLogger(__name__)

IST = zoneinfo.ZoneInfo('Asia/Kolkata')


@shared_task
def send_booking_confirmation(appointment_id):
    """Send booking confirmation to patient + notification to doctor."""
    try:
        appointment = Appointment.objects.select_related(
            'patient', 'doctor', 'clinic', 'slot'
        ).get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error(f"Appointment {appointment_id} not found")
        return

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

    logger.info(f"Booking confirmation sent for appointment {appointment_id}")


@shared_task
def send_day_before_reminders():
    """Send WhatsApp reminders for tomorrow's appointments. Runs daily at 6 PM IST."""
    tomorrow = date.today() + timedelta(days=1)
    appointments = Appointment.objects.filter(
        status='booked',
        slot__date=tomorrow,
    ).select_related('patient', 'doctor', 'slot', 'clinic')

    count = 0

    for appointment in appointments:
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

    logger.info(f"Sent {count} day-before reminders for {tomorrow}")
    return count


@shared_task
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
            logger.info(f"Max call attempts reached for appointment {appointment.id}")
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

    logger.info(f"Initiated {count} confirmation calls for {tomorrow}")
    return count


@shared_task
def handle_call_response(appointment_id, patient_response):
    """Handle patient's response from the automated call.
    patient_response: '1' = confirm, '2' = cancel
    """
    try:
        appointment = Appointment.objects.select_related(
            'patient', 'doctor', 'slot', 'clinic'
        ).get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error(f"Appointment {appointment_id} not found")
        return

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
        logger.info(f"Appointment {appointment_id} confirmed via call")

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

        logger.info(f"Appointment {appointment_id} cancelled via call")


@shared_task
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

    logger.info(f"Retried {count} unanswered calls")
    return count


@shared_task
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
                logger.error(f"[hour-before] Failed for appt {appt.id}: {result}")
                continue
        except Exception as e:
            logger.exception(f"[hour-before] Send crashed for appt {appt.id}: {e}")
            continue

        Appointment.objects.filter(pk=appt.pk, hour_before_reminded_at__isnull=True).update(
            hour_before_reminded_at=timezone.now()
        )
        logger.info(
            f"[hour-before] Sent to {appt.patient.whatsapp_number} "
            f"for appt {appt.id} ({appt.slot.date} {appt.slot.time})"
        )
        count += 1

    logger.info(f"[hour-before] Sent {count} reminder(s) in window {window_start.time()}–{window_end.time()}")
    return count


@shared_task
def fetch_daily_leads(top_n: int = 20):
    """Pull fresh clinic leads from Google Places API and save the top N as Lead rows.

    Calls the seed_leads management command — keeps the lead-gen logic in one place.
    Default 20 leads/day with strict score threshold for high conversion quality.
    """
    from django.core.management import call_command
    try:
        call_command('seed_leads', top=top_n)
    except Exception as e:
        logger.exception(f"[lead-gen] Failed: {e}")
        raise
