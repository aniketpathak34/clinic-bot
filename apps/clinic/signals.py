"""Signals for the clinic app.

- Sends a WhatsApp welcome to a doctor the first time they become registered.
  Idempotent via the Doctor.welcomed_at timestamp.
- Wipes a Patient's ConversationState when the Patient row is deleted, so the
  bot treats them as a fresh user (shows language picker again) on next contact.
"""
import logging
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.clinic.models import Doctor, Patient
from apps.observability import log
from apps.observability.context import new_trace, set_correlation

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Patient)
def clear_state_on_patient_delete(sender, instance: Patient, **kwargs):
    """Drop the ConversationState when a Patient row is removed from admin."""
    from apps.conversations.models import ConversationState
    new_trace()
    set_correlation(whatsapp_number=instance.whatsapp_number)
    deleted, _ = ConversationState.objects.filter(
        whatsapp_number=instance.whatsapp_number
    ).delete()
    if deleted:
        log.event('patient_state_cleared_on_delete',
                  message=f'Cleared ConversationState for …{instance.whatsapp_number[-4:]}',
                  deleted_count=deleted)
    log.flush(request_kind='other',
              inbound_text=f'patient_delete:{instance.whatsapp_number[-4:]}')


@receiver(post_save, sender=Doctor)
def greet_doctor_on_registration(sender, instance: Doctor, created, **kwargs):
    """Send a one-time welcome WhatsApp when a doctor becomes registered."""
    if not instance.is_registered:
        return
    if instance.welcomed_at is not None:
        return
    if not instance.whatsapp_number:
        return

    clinic = instance.clinic
    if not clinic or not clinic.phone_number_id:
        new_trace()
        set_correlation(clinic_id=instance.clinic_id,
                        whatsapp_number=instance.whatsapp_number)
        log.warn('welcome_skipped_no_pnid',
                 message=f'Skipping welcome for Dr. {instance.name}: clinic missing pnid',
                 doctor_id=instance.pk, doctor_name=instance.name)
        log.flush(request_kind='other', inbound_text='doctor_signal_no_pnid')
        return

    # Defer the send until the DB transaction commits — avoids sending if the
    # save gets rolled back (e.g. admin inline error).
    transaction.on_commit(lambda: _send_welcome(instance.pk))


def _send_welcome(doctor_pk: int):
    """Actually send the welcome. Separated so it's testable + safe from signal re-entry."""
    from apps.whatsapp.utils import get_whatsapp_service
    from bot_locale.messages import get_msg

    new_trace()

    try:
        doctor = Doctor.objects.select_related('clinic').get(pk=doctor_pk)
    except Doctor.DoesNotExist:
        log.flush(request_kind='other', inbound_text='doctor_gone_before_welcome')
        return

    if doctor.welcomed_at is not None:
        # racing signal guard
        log.flush(request_kind='other', inbound_text='already_welcomed')
        return

    clinic = doctor.clinic
    set_correlation(clinic_id=(clinic.id if clinic else None),
                    whatsapp_number=doctor.whatsapp_number)
    try:
        service = get_whatsapp_service(clinic=clinic)
        msg = get_msg(
            'en', 'doctor_welcome_onboarded',
            name=doctor.name, clinic_name=clinic.name,
        )
        result = service.send_message(doctor.whatsapp_number, msg)

        if result.get('status') == 'error':
            # Extract Meta error code so the admin row carries actionable detail
            meta_code = None
            try:
                import json as _json
                body = result.get('body') or '{}'
                if isinstance(body, str):
                    body = _json.loads(body)
                meta_code = (body.get('error') or {}).get('code')
            except Exception:
                pass

            if meta_code == 131030:
                log.warn('welcome_skipped_131030',
                         message='Recipient phone not on Meta allow-list',
                         doctor=doctor.name, doctor_id=doctor.pk,
                         meta_code=131030,
                         hint=f'Add {doctor.whatsapp_number} to WhatsApp Manager allow-list, OR switch the Meta app to Live mode')
            elif meta_code in (131047, 131051):
                log.warn('welcome_skipped_meta_policy',
                         message='Meta policy / unsupported message type',
                         doctor=doctor.name, meta_code=meta_code)
            else:
                log.error('welcome_failed',
                          message='Welcome send rejected by Meta',
                          doctor=doctor.name, meta_code=meta_code,
                          body=str(result)[:300])
            log.flush(request_kind='other',
                      inbound_text=f'welcome_skip:{doctor.name}')
            return

        Doctor.objects.filter(pk=doctor_pk, welcomed_at__isnull=True).update(
            welcomed_at=timezone.now()
        )
        log.event('welcome_sent',
                  message=f'Welcome WhatsApp sent to Dr. {doctor.name}',
                  doctor=doctor.name, doctor_id=doctor.pk,
                  clinic_code=clinic.clinic_code)
        log.flush(request_kind='other',
                  inbound_text=f'welcome:{doctor.name}')

    except Exception as e:
        log.error('welcome_unexpected_error', exc=e,
                  message=f'Unexpected error sending welcome to Dr. {doctor.name}',
                  doctor=doctor.name)
        log.flush(request_kind='other',
                  inbound_text=f'welcome_error:{doctor.name}')


@receiver(post_save, sender='clinic.Clinic')
def create_subscription_for_new_clinic(sender, instance, created, **kwargs):
    """Auto-seed a 30-day pilot Subscription whenever a Clinic is created."""
    if not created:
        return
    from datetime import date, timedelta
    from apps.subscriptions.models import Subscription
    Subscription.objects.get_or_create(
        clinic=instance,
        defaults={
            'tier':               'basic',
            'status':             'pilot',
            'started_at':         date.today(),
            'current_period_end': date.today() + timedelta(days=30),
            'pilot_ends_at':      date.today() + timedelta(days=30),
            'monthly_amount_inr': 0,
        },
    )
