from django.test import TestCase
from datetime import date, time

from apps.clinic.models import Clinic, Doctor, Patient, AvailableSlot, Appointment
from apps.conversations.models import ConversationState
from apps.conversations.engine import handle_message


class PatientLanguageAndMenuTest(TestCase):
    """New flow: Language select → Main menu directly (no registration)."""

    def test_language_select_shows_menu(self):
        phone = '919876543210'

        # Step 1: Send Hi → get language menu
        response = handle_message(phone, 'Hi')
        self.assertIn('choose your language', response.lower())

        # Step 2: Select English → should show main menu directly
        response = handle_message(phone, '1')
        self.assertIn('Book Appointment', response)

    def test_hindi_language_shows_menu(self):
        phone = '919876543211'

        handle_message(phone, 'Hi')
        response = handle_message(phone, '2')  # Hindi
        self.assertIn('अपॉइंटमेंट बुक करें', response)

    def test_marathi_language_shows_menu(self):
        phone = '919876543212'

        handle_message(phone, 'Hi')
        response = handle_message(phone, '3')  # Marathi
        self.assertIn('अपॉइंटमेंट बुक करा', response)


class PatientLazyRegistrationTest(TestCase):
    """Registration only happens when patient tries to book."""

    def setUp(self):
        self.clinic = Clinic.objects.create(name='Test Clinic', clinic_code='TC01')
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, name='Sharma', whatsapp_number='919888888888',
            specialty='general', is_registered=True
        )
        AvailableSlot.objects.create(doctor=self.doctor, date=date(2026, 3, 25), time=time(10, 0))

    def test_booking_triggers_registration(self):
        phone = '919876543210'

        # Language select
        handle_message(phone, 'Hi')
        handle_message(phone, '1')  # English → main menu

        # Try to book → should ask for name
        response = handle_message(phone, '1')
        self.assertIn('name', response.lower())

        # Enter name
        response = handle_message(phone, 'Rahul')
        self.assertIn('age', response.lower())

        # Enter age → should complete registration AND show doctors
        response = handle_message(phone, '28')
        self.assertIn('Registration complete', response)
        self.assertIn('Sharma', response)

        # Verify patient created
        patient = Patient.objects.get(whatsapp_number=phone)
        self.assertEqual(patient.name, 'Rahul')
        self.assertTrue(patient.is_registered)


class PatientBookingFlowTest(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name='Test Clinic', clinic_code='TC01')
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, name='Sharma', whatsapp_number='919888888888',
            specialty='general', is_registered=True
        )
        self.patient = Patient.objects.create(
            whatsapp_number='919876543210', name='Rahul', age=28,
            language_preference='en', is_registered=True
        )
        ConversationState.objects.create(
            whatsapp_number='919876543210', user_type='patient',
            current_flow='main_menu', language='en'
        )
        AvailableSlot.objects.create(doctor=self.doctor, date=date(2026, 3, 25), time=time(10, 0))
        AvailableSlot.objects.create(doctor=self.doctor, date=date(2026, 3, 25), time=time(14, 0))

    def test_booking_flow(self):
        phone = '919876543210'

        # Select Book Appointment
        response = handle_message(phone, '1')
        self.assertIn('Sharma', response)

        # Select doctor
        response = handle_message(phone, '1')
        self.assertIn('date', response.lower())

        # Select date
        response = handle_message(phone, '25-march')
        self.assertIn('10:00 AM', response)

        # Select slot
        response = handle_message(phone, '1')
        self.assertIn('Appointment booked', response)

        # Verify appointment created
        appointment = Appointment.objects.get(patient=self.patient)
        self.assertEqual(appointment.status, 'booked')
        self.assertEqual(appointment.doctor, self.doctor)

    def test_cancel_flow(self):
        phone = '919876543210'
        slot = AvailableSlot.objects.first()
        slot.is_booked = True
        slot.save()
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, clinic=self.clinic,
            slot=slot, status='booked'
        )

        # Select Cancel
        response = handle_message(phone, '3')
        self.assertIn('Sharma', response)

        # Cancel first appointment
        response = handle_message(phone, '1')
        self.assertIn('cancelled', response)

        slot.refresh_from_db()
        self.assertFalse(slot.is_booked)

    def test_view_appointments(self):
        phone = '919876543210'
        slot = AvailableSlot.objects.first()
        slot.is_booked = True
        slot.save()
        Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, clinic=self.clinic,
            slot=slot, status='booked'
        )

        response = handle_message(phone, '4')
        self.assertIn('Sharma', response)

    def test_reset_command(self):
        phone = '919876543210'
        response = handle_message(phone, 'reset')
        self.assertIn('reset', response.lower())


class PatientMenuNavigationTest(TestCase):
    def setUp(self):
        Patient.objects.create(
            whatsapp_number='919876543210', name='Rahul', age=28,
            language_preference='en', is_registered=True
        )
        ConversationState.objects.create(
            whatsapp_number='919876543210', user_type='patient',
            current_flow='main_menu', language='en'
        )

    def test_menu_command(self):
        response = handle_message('919876543210', 'menu')
        self.assertIn('Book Appointment', response)

    def test_invalid_menu_choice(self):
        response = handle_message('919876543210', '99')
        self.assertIn("didn't understand", response.lower())
