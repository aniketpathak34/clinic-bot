"""Interactive chat command for testing the bot locally."""
import sys
from django.core.management.base import BaseCommand
from apps.conversations.engine import handle_message


class Command(BaseCommand):
    help = 'Interactive chat session with the bot (for testing)'

    def add_arguments(self, parser):
        parser.add_argument('phone', type=str, help='Phone number to simulate (e.g., 919876543210)')

    def handle(self, *args, **options):
        phone = options['phone']
        self.stdout.write(self.style.SUCCESS(f"Chat session started for {phone}"))
        self.stdout.write("Type your messages below. Type 'quit' to exit.\n")
        self.stdout.write("-" * 50)

        while True:
            try:
                self.stdout.write("")
                user_input = input(f"\n📱 You ({phone}): ")
            except (EOFError, KeyboardInterrupt):
                self.stdout.write("\n\nChat session ended.")
                break

            if user_input.strip().lower() == 'quit':
                self.stdout.write("\nChat session ended.")
                break

            if not user_input.strip():
                continue

            response = handle_message(phone, user_input)
            self.stdout.write(f"\n🤖 Bot: {response}")
