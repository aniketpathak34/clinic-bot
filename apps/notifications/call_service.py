"""Automated call service for appointment confirmation.

Supports Twilio (production) and Mock (development).
Call flow: Call patient → Play message → Ask to press 1 (confirm) or 2 (cancel).
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# In-memory store for mock calls
_mock_calls = []


class MockCallService:
    """Mock call service that logs calls for testing."""

    def make_confirmation_call(self, to: str, patient_name: str, doctor_name: str,
                                appointment_date: str, appointment_time: str,
                                appointment_id: int, language: str = 'en') -> dict:
        call = {
            'to': to,
            'patient_name': patient_name,
            'doctor_name': doctor_name,
            'date': appointment_date,
            'time': appointment_time,
            'appointment_id': appointment_id,
            'language': language,
            'status': 'mock_initiated',
        }
        _mock_calls.append(call)
        logger.info(
            f"[MOCK Call] To: {to} | "
            f"Appointment: Dr. {doctor_name} on {appointment_date} at {appointment_time} | "
            f"Language: {language}"
        )
        return {'status': 'mock_initiated', 'call_id': f'mock_{len(_mock_calls)}'}

    @staticmethod
    def get_calls():
        return list(_mock_calls)

    @staticmethod
    def clear_calls():
        _mock_calls.clear()


class TwilioCallService:
    """Twilio-based automated call service.

    Requires: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER in settings.
    Also needs a publicly accessible webhook URL for call status callbacks.
    """

    def __init__(self):
        from twilio.rest import Client
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.from_number = settings.TWILIO_PHONE_NUMBER
        self.callback_url = getattr(settings, 'CALL_CALLBACK_URL', '')

    def make_confirmation_call(self, to: str, patient_name: str, doctor_name: str,
                                appointment_date: str, appointment_time: str,
                                appointment_id: int, language: str = 'en') -> dict:
        twiml = self._build_twiml(patient_name, doctor_name, appointment_date,
                                   appointment_time, appointment_id, language)

        call = self.client.calls.create(
            to=f'+{to}',
            from_=self.from_number,
            twiml=twiml,
            timeout=30,
            status_callback=f'{self.callback_url}/api/calls/status/',
            status_callback_event=['completed', 'no-answer', 'busy', 'failed'],
        )

        logger.info(f"[Twilio] Call initiated to {to}, SID: {call.sid}")
        return {'status': 'initiated', 'call_id': call.sid}

    def _build_twiml(self, patient_name, doctor_name, appointment_date,
                     appointment_time, appointment_id, language):
        messages = {
            'en': (
                f"Hello {patient_name}. This is a reminder for your appointment with "
                f"Doctor {doctor_name} on {appointment_date} at {appointment_time}. "
                f"Press 1 to confirm your appointment. Press 2 to cancel."
            ),
            'hi': (
                f"Namaste {patient_name}. Yeh aapki appointment ki yaad dilaane ke liye call hai. "
                f"Doctor {doctor_name} ke saath {appointment_date} ko {appointment_time} baje. "
                f"Confirm karne ke liye 1 dabayen. Cancel karne ke liye 2 dabayen."
            ),
            'mr': (
                f"Namaskar {patient_name}. Tumchya appointment chi aathvan karoon denyasaathi ha call ahe. "
                f"Doctor {doctor_name} yanchi {appointment_date} roji {appointment_time} vaajta. "
                f"Confirm karaycha asel tar 1 daba. Cancel karaycha asel tar 2 daba."
            ),
        }

        msg = messages.get(language, messages['en'])

        return f"""
        <Response>
            <Say language="{'hi-IN' if language == 'hi' else 'mr-IN' if language == 'mr' else 'en-IN'}">{msg}</Say>
            <Gather numDigits="1" action="{self.callback_url}/api/calls/gather/{appointment_id}/" method="POST" timeout="10">
                <Say>Please press 1 or 2 now.</Say>
            </Gather>
            <Say>We did not receive any input. Your appointment remains confirmed. Goodbye.</Say>
        </Response>
        """


def get_call_service():
    """Factory: returns the configured call service instance."""
    service_class = getattr(settings, 'CALL_SERVICE_CLASS',
                           'apps.notifications.call_service.MockCallService')
    from importlib import import_module
    module_path, class_name = service_class.rsplit('.', 1)
    module = import_module(module_path)
    cls = getattr(module, class_name)
    return cls()
