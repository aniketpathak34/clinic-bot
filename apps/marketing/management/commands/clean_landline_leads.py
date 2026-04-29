"""Find and (optionally) delete leads whose phone numbers are Indian landlines.

WhatsApp Business API can only message mobile numbers — landline leads
will always error on send, so they're noise in the pipeline.

Usage:
    python manage.py clean_landline_leads             # dry-run (just lists them)
    python manage.py clean_landline_leads --delete    # actually delete
"""
from django.core.management.base import BaseCommand

from apps.marketing.models import Lead
from apps.marketing.places import _is_mobile_phone


class Command(BaseCommand):
    help = "Find leads with non-mobile (landline) phones and optionally delete them."

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Actually delete the leads. Default is dry-run (just print).',
        )

    def handle(self, *args, **options):
        do_delete = options['delete']
        landlines = []
        for lead in Lead.objects.all():
            if not _is_mobile_phone(lead.phone):
                landlines.append(lead)

        if not landlines:
            self.stdout.write(self.style.SUCCESS(
                "✓ No landline leads found — all phones look like mobiles."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"Found {len(landlines)} lead(s) with landline / non-mobile phones:\n"
        ))
        for lead in landlines:
            self.stdout.write(f"  • {lead.phone:15}  {lead.name[:50]}  (status: {lead.status})")

        if do_delete:
            count = len(landlines)
            for lead in landlines:
                lead.delete()
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ Deleted {count} landline lead(s)."
            ))
        else:
            self.stdout.write("\n(Dry run — nothing deleted. Re-run with --delete to remove them.)")
