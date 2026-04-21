"""Seed one test clinic bound to the Meta test phone number.

Reads env vars so deploy can override without code changes:
  TEST_CLINIC_PHONE_NUMBER_ID      (required for webhook routing)
  TEST_CLINIC_DISPLAY_PHONE_NUMBER (required)
  TEST_CLINIC_OWNER_NUMBER         (optional — for daily summary)
  TEST_CLINIC_DOCTOR_NUMBER        (optional — the doctor WhatsApp)
"""
import os
from django.core.management.base import BaseCommand
from apps.clinic.models import Clinic, Doctor


class Command(BaseCommand):
    help = 'Seed a test clinic wired to the Meta test phone number'

    def handle(self, *args, **options):
        phone_number_id = os.getenv('TEST_CLINIC_PHONE_NUMBER_ID', '').strip()
        display_number = os.getenv('TEST_CLINIC_DISPLAY_PHONE_NUMBER', '').strip().lstrip('+')
        owner_number = os.getenv('TEST_CLINIC_OWNER_NUMBER', '').strip().lstrip('+')
        doctor_number = os.getenv('TEST_CLINIC_DOCTOR_NUMBER', '').strip().lstrip('+')

        if not phone_number_id or not display_number:
            self.stdout.write(self.style.WARNING(
                'Skipping seed: set TEST_CLINIC_PHONE_NUMBER_ID and '
                'TEST_CLINIC_DISPLAY_PHONE_NUMBER in environment.'
            ))
            return

        clinic, created = Clinic.objects.update_or_create(
            clinic_code='TEST01',
            defaults={
                'name': 'Test Clinic',
                'whatsapp_number': display_number,
                'display_phone_number': display_number,
                'phone_number_id': phone_number_id,
                'owner_number': owner_number,
                'address': 'Pune (test)',
                'working_hours': 'Mon-Sat 9am-8pm',
                'working_days': 'Mon-Sat',
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'}: {clinic} "
            f"(phone_number_id={phone_number_id}, display={display_number})"
        ))

        if doctor_number:
            doc, d_created = Doctor.objects.update_or_create(
                whatsapp_number=doctor_number,
                defaults={
                    'clinic': clinic,
                    'name': 'Test Doctor',
                    'specialty': 'general',
                    'is_registered': True,
                },
            )
            self.stdout.write(self.style.SUCCESS(
                f"{'Created' if d_created else 'Updated'}: {doc}"
            ))
