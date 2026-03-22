"""Generate QR codes for clinics.

Usage:
    python manage.py generate_qr                # All clinics
    python manage.py generate_qr TC01           # Specific clinic
    python manage.py generate_qr --list         # List all clinic codes
"""
import os
import qrcode
from django.conf import settings
from django.core.management.base import BaseCommand
from apps.clinic.models import Clinic


BOT_WHATSAPP_NUMBER = os.getenv('MSG91_INTEGRATED_NUMBER', '917020162229')


class Command(BaseCommand):
    help = 'Generate WhatsApp QR codes for clinic onboarding'

    def add_arguments(self, parser):
        parser.add_argument('clinic_code', nargs='?', default=None, help='Specific clinic code')
        parser.add_argument('--list', action='store_true', help='List all clinic codes')

    def handle(self, *args, **options):
        if options['list']:
            clinics = Clinic.objects.all()
            for c in clinics:
                self.stdout.write(f"  {c.clinic_code} — {c.name} ({c.address})")
            return

        if options['clinic_code']:
            clinics = Clinic.objects.filter(clinic_code=options['clinic_code'].upper())
            if not clinics.exists():
                self.stderr.write(self.style.ERROR(f"Clinic '{options['clinic_code']}' not found"))
                return
        else:
            clinics = Clinic.objects.all()

        # Create output directory
        qr_dir = os.path.join(settings.BASE_DIR, 'qr_codes')
        os.makedirs(qr_dir, exist_ok=True)

        for clinic in clinics:
            wa_link = f"https://wa.me/{BOT_WHATSAPP_NUMBER}?text={clinic.clinic_code}"

            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(wa_link)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")

            filename = f"{clinic.clinic_code}.png"
            filepath = os.path.join(qr_dir, filename)
            img.save(filepath)

            self.stdout.write(self.style.SUCCESS(
                f"✅ {clinic.name} ({clinic.clinic_code})\n"
                f"   Link: {wa_link}\n"
                f"   QR:   {filepath}\n"
            ))

        self.stdout.write(self.style.SUCCESS(f"\nAll QR codes saved to: {qr_dir}"))
