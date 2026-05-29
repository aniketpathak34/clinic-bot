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

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Patient)
def clear_state_on_patient_delete(sender, instance: Patient, **kwargs):
    """Drop the ConversationState when a Patient row is removed from admin."""
    from apps.conversations.models import ConversationState
    deleted, _ = ConversationState.objects.filter(
        whatsapp_number=instance.whatsapp_number
    ).delete()
    if deleted:
        logger.info(
            f"[patient-delete] Cleared ConversationState for {instance.whatsapp_number}"
        )


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
            # Try to extract Meta's error code — some failures are expected
            # config issues, not engineering bugs. Log those as WARNING with
            # a single actionable line; only unknown failures stay ERROR.
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
                # Recipient phone number not on the Meta test-mode allow-list.
                # Expected during development — not an engineering failure.
                logger.warning(
                    "[welcome] skipped doctor=%s wa=%s reason=meta_131030 "
                    "fix='Add %s to WhatsApp Manager > Phone numbers > To list, "
                    "or switch the Meta app to Live mode'",
                    doctor.name, doctor.whatsapp_number, doctor.whatsapp_number,
                )
            elif meta_code in (131047, 131051):
                # 131047: re-engagement window expired (24h rule)
                # 131051: unsupported message type — both are config/policy, not bugs
                logger.warning(
                    "[welcome] skipped doctor=%s wa=%s meta_code=%s",
                    doctor.name, doctor.whatsapp_number, meta_code,
                )
            else:
                logger.error(
                    "[welcome] failed doctor=%s wa=%s meta_code=%s body=%s",
                    doctor.name, doctor.whatsapp_number, meta_code, result,
                )
            return

        Doctor.objects.filter(pk=doctor_pk, welcomed_at__isnull=True).update(
            welcomed_at=timezone.now()
        )
        logger.info(
            "[welcome] sent doctor=%s wa=%s clinic=%s",
            doctor.name, doctor.whatsapp_number, clinic.clinic_code,
        )

    except Exception as e:
        logger.exception(
            "[welcome] unexpected_error doctor=%s wa=%s err=%s",
            doctor.name, doctor.whatsapp_number, e,
        )
