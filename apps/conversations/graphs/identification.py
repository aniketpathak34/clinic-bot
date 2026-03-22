"""Identify user type and clinic from incoming message."""
from apps.clinic.models import Clinic, Doctor, Patient


def identify_user(phone: str, text: str) -> tuple:
    """Determine user type and clinic from phone number and message.

    Returns (user_type, clinic_or_none)

    Flow:
    1. Known doctor (by phone) → 'doctor', their clinic
    2. Known patient (by phone) → 'patient', None (clinic set later or from context)
    3. Message is a clinic code → 'patient', that clinic
    4. Unknown → 'unknown', None
    """
    # Check if registered doctor
    doctor = Doctor.objects.filter(whatsapp_number=phone, is_registered=True).select_related('clinic').first()
    if doctor:
        return 'doctor', doctor.clinic

    # Check if registered patient
    if Patient.objects.filter(whatsapp_number=phone, is_registered=True).exists():
        return 'patient', None

    # Check if the message is a clinic code
    clinic = try_parse_clinic_code(text)
    if clinic:
        return 'patient', clinic

    # Unknown user, no clinic context
    return 'unknown', None


def try_parse_clinic_code(text: str):
    """Try to extract a clinic code from the message.

    Handles formats:
    - "SHARMA01" (just the code)
    - "clinic SHARMA01"
    - "hi SHARMA01"
    - URL pre-filled text from QR code
    """
    text = text.strip().upper()

    # Direct clinic code match
    clinic = Clinic.objects.filter(clinic_code=text).first()
    if clinic:
        return clinic

    # Try each word in the message
    for word in text.split():
        word = word.strip()
        clinic = Clinic.objects.filter(clinic_code=word).first()
        if clinic:
            return clinic

    return None
