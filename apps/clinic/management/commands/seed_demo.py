"""Seed a full demo dataset on top of an empty clinic bot DB.

Idempotent — safe to run on every deploy. Creates:
  * Dr. Aniket Pathak (or whoever DEMO_DOCTOR_* env vars point to) under TEST01
  * 3 weeks of AvailableSlot rows from the clinic's operating hours
  * 8 demo patients (Indian names, test phone numbers starting 91810000…)
  * 8 demo appointments — 3 today, 5 upcoming — showcasing Today's/Upcoming views
  * The first superuser's landing-page contact fields if they are blank

Env vars honored:
  DEMO_DOCTOR_NAME              default "Aniket Pathak"
  DEMO_DOCTOR_WHATSAPP_NUMBER   default "917030344210"
  DEMO_DOCTOR_SPECIALTY         default "general"
  DJANGO_SUPERUSER_BOT_NUMBER, DJANGO_SUPERUSER_CONTACT_NUMBER,
  DJANGO_SUPERUSER_CONTACT_NAME  — only applied if the superuser has these blank
"""
import os
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.clinic.models import Appointment, AvailableSlot, Clinic, Doctor, Patient

# Fake patients: (whatsapp_number, name, age)
DEMO_PATIENTS = [
    ('918100000101', 'Rahul Sharma', 34),
    ('918100000102', 'Priya Desai', 28),
    ('918100000103', 'Amit Joshi', 45),
    ('918100000104', 'Neha Kulkarni', 31),
    ('918100000105', 'Rohan Kamble', 52),
    ('918100000106', 'Sneha Patil', 22),
    ('918100000107', 'Vikram Iyer', 40),
    ('918100000108', 'Kavita Nair', 38),
]

# Booking schedule: (days_from_today, time, patient_index)
DEMO_BOOKINGS = [
    # TODAY (3 appointments for "Today's Bookings" screenshot)
    (0, time(9, 30), 0),
    (0, time(11, 0), 1),
    (0, time(17, 0), 2),
    # TOMORROW
    (1, time(10, 0), 3),
    (1, time(18, 30), 4),
    # DAY AFTER
    (2, time(11, 30), 5),
    # NEXT WEEK
    (5, time(9, 0), 6),
    (6, time(19, 0), 7),
]


class Command(BaseCommand):
    help = "Seed the demo dataset: doctor, slots, patients, appointments, superuser contact fields."

    def handle(self, *args, **options):
        try:
            clinic = Clinic.objects.get(clinic_code='TEST01')
        except Clinic.DoesNotExist:
            self.stdout.write(self.style.WARNING(
                "Clinic TEST01 not found — run `seed_data` first, then re-run `seed_demo`."
            ))
            return

        self._seed_superuser_fields()
        doctor = self._seed_doctor(clinic)
        slot_count = self._seed_slots(doctor, clinic)
        patients = self._seed_patients()
        appt_count = self._seed_appointments(doctor, clinic, patients)

        self.stdout.write(self.style.SUCCESS(
            f"Demo ready — doctor: Dr. {doctor.name} | "
            f"{slot_count} slots | {len(patients)} patients | {appt_count} appointments"
        ))

    def _seed_superuser_fields(self):
        """Populate landing-page contact fields on the first superuser if blank."""
        User = get_user_model()
        user = User.objects.filter(is_superuser=True).order_by('id').first()
        if not user:
            return

        updated = []
        for field, env_key, default in [
            ('bot_number', 'DJANGO_SUPERUSER_BOT_NUMBER', '15551773718'),
            ('contact_number', 'DJANGO_SUPERUSER_CONTACT_NUMBER', '917030344210'),
            ('contact_name', 'DJANGO_SUPERUSER_CONTACT_NAME', 'Aniket'),
        ]:
            if not getattr(user, field, ''):
                value = (os.environ.get(env_key, '') or default).strip()
                setattr(user, field, value)
                updated.append(field)

        if updated:
            user.save(update_fields=updated)
            self.stdout.write(self.style.SUCCESS(
                f"Superuser '{user.username}' landing fields set: {', '.join(updated)}"
            ))

    def _seed_doctor(self, clinic):
        name = os.environ.get('DEMO_DOCTOR_NAME', 'Aniket Pathak').strip()
        number = os.environ.get('DEMO_DOCTOR_WHATSAPP_NUMBER', '917030344210').strip().lstrip('+')
        specialty = os.environ.get('DEMO_DOCTOR_SPECIALTY', 'general').strip()

        doctor, created = Doctor.objects.update_or_create(
            whatsapp_number=number,
            defaults={
                'clinic': clinic,
                'name': name,
                'specialty': specialty,
                'is_registered': True,
            },
        )
        self.stdout.write(f"Doctor: Dr. {doctor.name} ({'created' if created else 'exists'})")
        return doctor

    def _seed_slots(self, doctor, clinic):
        """Fill 21 days of AvailableSlot rows from the clinic's operating hours."""
        today = date.today()
        created = 0
        for offset in range(21):
            d = today + timedelta(days=offset)
            if not clinic.is_open(d):
                continue
            for t in clinic.get_slot_times(d):
                _, was_created = AvailableSlot.objects.get_or_create(
                    doctor=doctor, date=d, time=t,
                    defaults={'is_booked': False},
                )
                if was_created:
                    created += 1
        return created

    def _seed_patients(self):
        patients = []
        for phone, name, age in DEMO_PATIENTS:
            p, _ = Patient.objects.update_or_create(
                whatsapp_number=phone,
                defaults={'name': name, 'age': age,
                          'language_preference': 'en', 'is_registered': True},
            )
            patients.append(p)
        return patients

    def _seed_appointments(self, doctor, clinic, patients):
        today = date.today()
        count = 0
        for offset, t, idx in DEMO_BOOKINGS:
            d = today + timedelta(days=offset)
            if not clinic.is_open(d):
                continue
            if t not in clinic.get_slot_times(d):
                continue  # slot outside operating hours
            slot, _ = AvailableSlot.objects.get_or_create(doctor=doctor, date=d, time=t)
            patient = patients[idx]
            # Skip if this patient already has a booked appointment in this slot
            if Appointment.objects.filter(
                patient=patient, slot=slot, status='booked'
            ).exists():
                continue
            slot.is_booked = True
            slot.save()
            Appointment.objects.create(
                patient=patient, doctor=doctor, clinic=clinic,
                slot=slot, status='booked',
            )
            count += 1
        return count

