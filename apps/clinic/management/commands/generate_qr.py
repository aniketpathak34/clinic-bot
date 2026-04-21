"""Generate QR codes for clinics.

With multi-clinic Meta setup, each clinic has its own WhatsApp number
(Clinic.display_phone_number). The QR links directly to that number — no
clinic code needed, since the inbound number identifies the clinic.

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


class Command(BaseCommand):
    help = 'Generate WhatsApp QR codes for clinic onboarding'

    def add_arguments(self, parser):
        parser.add_argument('clinic_code', nargs='?', default=None, help='Specific clinic code')
        parser.add_argument('--list', action='store_true', help='List all clinic codes')

    def handle(self, *args, **options):
        if options['list']:
            for c in Clinic.objects.all():
                self.stdout.write(f"  {c.clinic_code} — {c.name} ({c.display_phone_number or c.whatsapp_number or 'no number'})")
            return

        if options['clinic_code']:
            clinics = Clinic.objects.filter(clinic_code=options['clinic_code'].upper())
            if not clinics.exists():
                self.stderr.write(self.style.ERROR(f"Clinic '{options['clinic_code']}' not found"))
                return
        else:
            clinics = Clinic.objects.all()

        qr_dir = os.path.join(settings.BASE_DIR, 'qr_codes')
        os.makedirs(qr_dir, exist_ok=True)

        for clinic in clinics:
            number = (clinic.display_phone_number or clinic.whatsapp_number or '').lstrip('+')
            if not number:
                self.stderr.write(self.style.WARNING(
                    f"⚠️  Skipping {clinic.clinic_code} — no display_phone_number set"
                ))
                continue

            # Pre-filled text helps route new conversations even before the webhook.
            wa_link = f"https://wa.me/{number}?text=Hi"

            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(wa_link)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")
            filepath = os.path.join(qr_dir, f"{clinic.clinic_code}.png")
            img.save(filepath)

            self.stdout.write(self.style.SUCCESS(
                f"✅ {clinic.name} ({clinic.clinic_code})\n"
                f"   Link: {wa_link}\n"
                f"   QR:   {filepath}\n"
            ))

        self.stdout.write(self.style.SUCCESS(f"\nAll QR codes saved to: {qr_dir}"))
