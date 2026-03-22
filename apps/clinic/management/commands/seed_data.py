from django.core.management.base import BaseCommand
from apps.clinic.models import Clinic, Doctor


class Command(BaseCommand):
    help = 'Create seed data for testing'

    def handle(self, *args, **options):
        # Clinic 1
        clinic1, created = Clinic.objects.get_or_create(
            clinic_code='TC01',
            defaults={
                'name': 'Sharma Clinic',
                'whatsapp_number': '919999999999',
                'address': 'Kothrud, Pune',
            }
        )
        status = 'Created' if created else 'Exists'
        self.stdout.write(f'{status}: {clinic1}')

        # Doctor for Clinic 1 (pre-registered via admin)
        doc1, created = Doctor.objects.get_or_create(
            whatsapp_number='919888888888',
            defaults={
                'clinic': clinic1,
                'name': 'Sharma',
                'specialty': 'general',
                'is_registered': True,
            }
        )
        status = 'Created' if created else 'Exists'
        self.stdout.write(f'{status}: {doc1}')

        # Clinic 2
        clinic2, created = Clinic.objects.get_or_create(
            clinic_code='PATIL01',
            defaults={
                'name': 'Patil Dental Clinic',
                'whatsapp_number': '919777777777',
                'address': 'Aundh, Pune',
            }
        )
        status = 'Created' if created else 'Exists'
        self.stdout.write(f'{status}: {clinic2}')

        doc2, created = Doctor.objects.get_or_create(
            whatsapp_number='919666666666',
            defaults={
                'clinic': clinic2,
                'name': 'Patil',
                'specialty': 'dentist',
                'is_registered': True,
            }
        )
        status = 'Created' if created else 'Exists'
        self.stdout.write(f'{status}: {doc2}')

        self.stdout.write(self.style.SUCCESS('\nSeed data ready!'))
        self.stdout.write(self.style.SUCCESS(f'\nClinic links:'))
        for clinic in Clinic.objects.all():
            self.stdout.write(f'  {clinic.name}: wa.me/917020162229?text={clinic.clinic_code}')
