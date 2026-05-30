"""Walk Doctor, Patient, ConversationState — report or fix phone-number drift.

Dry-run by default:
    python manage.py normalize_existing_phones

Apply changes for real:
    python manage.py normalize_existing_phones --apply

The command:
  • Lists every row whose whatsapp_number differs from its canonical form
  • Flags rows whose value cannot be normalized at all (ValueError)
  • Flags collisions where two rows would normalize to the same value
    (BEFORE attempting to save — protects the unique constraint)
"""
from django.core.management.base import BaseCommand

from apps.clinic.models import Doctor, Patient
from apps.conversations.models import ConversationState
from apps.utils.phone import normalize_phone


class Command(BaseCommand):
    help = 'Normalize whatsapp_number across Doctor, Patient, ConversationState.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually write changes (default: dry-run, no DB writes)',
        )

    def handle(self, *args, **opts):
        apply_changes = opts['apply']
        banner = 'APPLY' if apply_changes else 'DRY-RUN'
        self.stdout.write(self.style.WARNING(
            f'\n  ╔═══ normalize_existing_phones ═══╗  Mode: {banner}\n'
        ))

        models = (
            ('Doctor',             Doctor),
            ('Patient',            Patient),
            ('ConversationState',  ConversationState),
        )

        total_changed = total_errors = total_collisions = total_skipped = 0

        for label, model in models:
            self.stdout.write(self.style.HTTP_INFO(f'  ── {label} ──'))
            changed = skipped = errors = collisions = 0

            for row in model.objects.all().order_by('pk'):
                raw = row.whatsapp_number or ''
                if not raw:
                    continue

                try:
                    canonical = normalize_phone(raw)
                except ValueError as e:
                    self.stdout.write(self.style.ERROR(
                        f'    ✗ id={row.pk:<5} wa={raw!r:<22} CANNOT NORMALIZE: {e}'
                    ))
                    errors += 1
                    continue

                if canonical == raw:
                    skipped += 1
                    continue

                # Look for a row that already has the canonical value —
                # would cause a unique-constraint violation on save
                colliding = (model.objects.filter(whatsapp_number=canonical)
                                          .exclude(pk=row.pk).first())
                if colliding:
                    self.stdout.write(self.style.WARNING(
                        f'    ⚠ id={row.pk:<5} wa={raw!r:<22} → {canonical!r:<14} '
                        f'COLLIDES with id={colliding.pk} — manual review needed'
                    ))
                    collisions += 1
                    continue

                self.stdout.write(
                    f'    → id={row.pk:<5} wa={raw!r:<22} → {canonical!r}'
                )
                changed += 1

                if apply_changes:
                    row.whatsapp_number = canonical
                    row.save(update_fields=['whatsapp_number'])

            self.stdout.write(self.style.SUCCESS(
                f'    {label}: changed={changed} skipped={skipped} '
                f'errors={errors} collisions={collisions}\n'
            ))
            total_changed += changed
            total_errors += errors
            total_collisions += collisions
            total_skipped += skipped

        self.stdout.write(self.style.SUCCESS(
            f'\n  Totals: {total_changed} changed · {total_skipped} already canonical · '
            f'{total_errors} errors · {total_collisions} collisions'
        ))
        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\n  Dry-run only — no writes. Re-run with --apply to commit.\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('\n  Changes committed.\n'))
