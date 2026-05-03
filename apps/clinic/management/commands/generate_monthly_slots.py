"""Fill AvailableSlot rows for an entire calendar month.

Run once a month (via the cron webhook) so that the demo doctor always has
fresh slots stretching to the end of the current month — that's what we
show to leads who land on the public booking page.

Usage:
    # Default — fill remaining days of the CURRENT month
    python manage.py generate_monthly_slots

    # Explicit month (YYYY-MM)
    python manage.py generate_monthly_slots --month 2026-06

    # A different doctor / clinic
    python manage.py generate_monthly_slots --clinic TEST01 --doctor 917030344210

The command is idempotent: re-running it never duplicates rows because
AvailableSlot.unique_together = ('doctor', 'date', 'time'). Slots in the
past are skipped. Closed days (per the clinic's operating hours) are
skipped too.
"""
import calendar
import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.clinic.models import AvailableSlot, Clinic, Doctor


class Command(BaseCommand):
    help = "Generate AvailableSlot rows for an entire calendar month for the demo doctor."

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            help="Target month as YYYY-MM. Defaults to the current month.",
        )
        parser.add_argument(
            '--clinic',
            default=os.environ.get('DEMO_CLINIC_CODE', 'TEST01'),
            help="Clinic code that owns the demo doctor (default TEST01).",
        )
        parser.add_argument(
            '--doctor',
            default=os.environ.get('DEMO_DOCTOR_WHATSAPP_NUMBER', '917030344210'),
            help="Doctor's WhatsApp number (default from DEMO_DOCTOR_WHATSAPP_NUMBER env, or 917030344210).",
        )

    def handle(self, *args, **options):
        # ── Resolve target month ────────────────────────────────────────
        if options['month']:
            try:
                year, month = (int(p) for p in options['month'].split('-'))
                if not (1 <= month <= 12):
                    raise ValueError
            except (ValueError, AttributeError):
                raise CommandError("--month must be in YYYY-MM format (e.g. 2026-06)")
        else:
            today = date.today()
            year, month = today.year, today.month

        first_day = date(year, month, 1)
        _, last_dom = calendar.monthrange(year, month)
        last_day = date(year, month, last_dom)
        # Don't backfill the past — start from today if we're inside the month.
        start_day = max(first_day, date.today())

        # ── Resolve clinic + doctor ─────────────────────────────────────
        clinic_code = options['clinic']
        try:
            clinic = Clinic.objects.get(clinic_code=clinic_code)
        except Clinic.DoesNotExist:
            raise CommandError(f"Clinic '{clinic_code}' not found. Run `seed_data` first.")

        doctor_number = options['doctor'].strip().lstrip('+')
        try:
            doctor = Doctor.objects.get(whatsapp_number=doctor_number, clinic=clinic)
        except Doctor.DoesNotExist:
            raise CommandError(
                f"Doctor with whatsapp_number={doctor_number} not found in clinic '{clinic_code}'. "
                f"Run `seed_demo` first to create the demo doctor."
            )

        # ── Fill the month, day by day ──────────────────────────────────
        created = skipped_closed = skipped_existing = 0
        cur = start_day
        while cur <= last_day:
            if not clinic.is_open(cur):
                skipped_closed += 1
                cur = self._next_day(cur)
                continue
            for t in clinic.get_slot_times(cur):
                _, was_created = AvailableSlot.objects.get_or_create(
                    doctor=doctor, date=cur, time=t,
                    defaults={'is_booked': False},
                )
                if was_created:
                    created += 1
                else:
                    skipped_existing += 1
            cur = self._next_day(cur)

        msg = (
            f"✓ {first_day.strftime('%B %Y')} for Dr. {doctor.name}: "
            f"created {created} new slot(s), {skipped_existing} already existed, "
            f"{skipped_closed} closed day(s) skipped "
            f"(window: {start_day.isoformat()} → {last_day.isoformat()})."
        )
        self.stdout.write(self.style.SUCCESS(msg))

    @staticmethod
    def _next_day(d: date) -> date:
        from datetime import timedelta
        return d + timedelta(days=1)
