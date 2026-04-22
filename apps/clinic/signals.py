"""Signals for the clinic app.

Sends a WhatsApp welcome to a doctor the first time they become registered.
Idempotent via the Doctor.welcomed_at timestamp.
"""
import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.clinic.models import Doctor

logger = logging.getLogger(__name__)


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
        logger.warning(
            f"Skipping welcome for Dr. {instance.name}: clinic has no phone_number_id"
        )
        return

    # Defer the send until the DB transaction commits — avoids sending if the
    # save gets rolled back (e.g. admin inline error).
    transaction.on_commit(lambda: _send_welcome(instance.pk))


def _send_welcome(doctor_pk: int):
    """Actually send the welcome. Separated so it's testable + safe from signal re-entry."""
    from apps.whatsapp.utils import get_whatsapp_service
    from bot_locale.messages import get_msg

    try:
        doctor = Doctor.objects.select_related('clinic').get(pk=doctor_pk)
    except Doctor.DoesNotExist:
        return

    if doctor.welcomed_at is not None:
        return  # racing signal guard

    clinic = doctor.clinic
    try:
        service = get_whatsapp_service(clinic=clinic)
        msg = get_msg(
            'en', 'doctor_welcome_onboarded',
            name=doctor.name, clinic_name=clinic.name,
        )
        result = service.send_message(doctor.whatsapp_number, msg)

        if result.get('status') == 'error':
            logger.error(
                f"[welcome] Failed to send to Dr. {doctor.name} "
                f"({doctor.whatsapp_number}): {result}"
            )
            return

        Doctor.objects.filter(pk=doctor_pk, welcomed_at__isnull=True).update(
            welcomed_at=timezone.now()
        )
        logger.info(f"[welcome] Sent to Dr. {doctor.name} at {doctor.whatsapp_number}")

    except Exception as e:
        logger.exception(f"[welcome] Unexpected error for Dr. {doctor.name}: {e}")
