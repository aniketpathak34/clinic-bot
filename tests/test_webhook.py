from django.test import TestCase, Client, override_settings


@override_settings(WHATSAPP_VERIFY_TOKEN='test-verify-token')
class WebhookVerificationTest(TestCase):
    def test_webhook_verify_success(self):
        client = Client()
        response = client.get('/api/webhook/whatsapp/', {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'test-verify-token',
            'hub.challenge': 'test_challenge_123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), 'test_challenge_123')

    def test_webhook_verify_wrong_token(self):
        client = Client()
        response = client.get('/api/webhook/whatsapp/', {
            'hub.mode': 'subscribe',
            'hub.verify_token': 'wrong-token',
            'hub.challenge': 'test_challenge',
        })
        self.assertEqual(response.status_code, 403)


class TestEndpointTest(TestCase):
    def test_send_message(self):
        client = Client()
        response = client.post('/api/test/send/',
            data='{"from": "919876543210", "message": "Hi"}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('bot_reply', data)
        self.assertIn('language', data['bot_reply'].lower())

    def test_get_messages(self):
        client = Client()
        response = client.get('/api/test/messages/')
        self.assertEqual(response.status_code, 200)

    def test_conversation_state_not_found(self):
        client = Client()
        response = client.get('/api/test/conversation/999999999/')
        self.assertEqual(response.status_code, 404)
