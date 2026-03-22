from django.test import TestCase
from apps.clinic.models import Clinic, Doctor, Patient, AvailableSlot, Appointment
from datetime import date, time


class ClinicModelTest(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            name='Test Clinic', clinic_code='TC01', address='Pune'
        )

    def test_clinic_str(self):
        self.assertEqual(str(self.clinic), 'Test Clinic (TC01)')

    def test_clinic_code_unique(self):
        with self.assertRaises(Exception):
            Clinic.objects.create(name='Another', clinic_code='TC01')


class DoctorModelTest(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name='Test Clinic', clinic_code='TC01')
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, name='Sharma', whatsapp_number='919888888888',
            specialty='general', is_registered=True
        )

    def test_doctor_str(self):
        self.assertIn('Sharma', str(self.doctor))

    def test_doctor_phone_unique(self):
        with self.assertRaises(Exception):
            Doctor.objects.create(
                clinic=self.clinic, name='Patil', whatsapp_number='919888888888'
            )


class PatientModelTest(TestCase):
    def test_patient_creation(self):
        patient = Patient.objects.create(
            whatsapp_number='919876543210', name='Rahul', age=28,
            language_preference='en', is_registered=True
        )
        self.assertEqual(str(patient), 'Rahul (919876543210)')


class AppointmentFlowTest(TestCase):
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
        self.slot = AvailableSlot.objects.create(
            doctor=self.doctor, date=date(2026, 3, 25), time=time(10, 0)
        )

    def test_book_appointment(self):
        appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, clinic=self.clinic,
            slot=self.slot, status='booked'
        )
        self.slot.is_booked = True
        self.slot.save()

        self.assertEqual(appointment.status, 'booked')
        self.assertTrue(self.slot.is_booked)

    def test_cancel_appointment(self):
        appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, clinic=self.clinic,
            slot=self.slot, status='booked'
        )
        self.slot.is_booked = True
        self.slot.save()

        appointment.status = 'cancelled'
        appointment.save()
        self.slot.is_booked = False
        self.slot.save()

        self.assertEqual(appointment.status, 'cancelled')
        self.assertFalse(self.slot.is_booked)
