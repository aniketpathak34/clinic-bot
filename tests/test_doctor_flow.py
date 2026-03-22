from django.test import TestCase
from datetime import date

from apps.clinic.models import Clinic, Doctor, AvailableSlot
from apps.conversations.models import ConversationState
from apps.conversations.engine import handle_message


class DoctorRegistrationFlowTest(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name='Test Clinic', clinic_code='TC01')

    def test_full_registration(self):
        phone = '919777777777'

        # Send "doctor" to trigger doctor flow
        response = handle_message(phone, 'doctor')
        self.assertIn('clinic code', response.lower())

        # Enter clinic code
        response = handle_message(phone, 'TC01')
        self.assertIn('name', response.lower())

        # Enter name
        response = handle_message(phone, 'Patil')
        self.assertIn('specialty', response.lower())

        # Select specialty
        response = handle_message(phone, '2')  # Dentist
        self.assertIn('Registration complete', response)
        self.assertIn('Patil', response)

        # Verify doctor created
        doctor = Doctor.objects.get(whatsapp_number=phone)
        self.assertEqual(doctor.name, 'Patil')
        self.assertEqual(doctor.specialty, 'dentist')
        self.assertTrue(doctor.is_registered)

    def test_invalid_clinic_code(self):
        phone = '919777777778'

        handle_message(phone, 'doctor')
        response = handle_message(phone, 'INVALID')
        self.assertIn('Invalid clinic code', response)


class DoctorAvailabilityTest(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name='Test Clinic', clinic_code='TC01')
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, name='Sharma', whatsapp_number='919888888888',
            specialty='general', is_registered=True
        )
        ConversationState.objects.create(
            whatsapp_number='919888888888', user_type='doctor',
            current_flow='doctor_menu', language='en'
        )

    def test_set_availability(self):
        phone = '919888888888'

        # Select Set Availability
        response = handle_message(phone, '1')
        self.assertIn('available', response.lower())

        # Send availability
        response = handle_message(phone, 'available 25-march 10am 2pm 4pm')
        self.assertIn('Slots saved', response)

        # Verify slots created
        slots = AvailableSlot.objects.filter(doctor=self.doctor, date=date(2026, 3, 25))
        self.assertEqual(slots.count(), 3)

    def test_view_bookings_empty(self):
        phone = '919888888888'
        response = handle_message(phone, '2')
        self.assertIn('No bookings', response)


class DoctorMenuTest(TestCase):
    def setUp(self):
        clinic = Clinic.objects.create(name='Test Clinic', clinic_code='TC01')
        Doctor.objects.create(
            clinic=clinic, name='Sharma', whatsapp_number='919888888888',
            specialty='general', is_registered=True
        )
        ConversationState.objects.create(
            whatsapp_number='919888888888', user_type='doctor',
            current_flow='doctor_menu', language='en'
        )

    def test_menu_command(self):
        response = handle_message('919888888888', 'menu')
        self.assertIn('Set Availability', response)
