"""Seed django-celery-beat with the project's recurring tasks.

Idempotent — safe to run on every deploy (build.sh calls this).
After running, schedules are visible + editable at:

    /admin/django_celery_beat/periodictask/

Admins can:
  - Enable / disable any task (uncheck "Enabled")
  - Edit the crontab (e.g. change 9 AM → 8 AM)
  - Trigger a one-off run via the admin action "Run selected tasks"
  - Add brand-new tasks without code change
"""
from django.core.management.base import BaseCommand


# (name, task_path, minute, hour, day_of_week, day_of_month, month_of_year, description)
SCHEDULES = [
    (
        'daily-lead-generation',
        'apps.notifications.tasks.fetch_daily_leads',
        '0', '9', '*', '*', '*',
        'Fetch 10 fresh clinic leads via Google Places API',
    ),
    (
        'day-before-reminders',
        'apps.notifications.tasks.send_day_before_reminders',
        '0', '18', '*', '*', '*',
        'Send 6 PM IST WhatsApp reminders for tomorrow\'s appointments',
    ),
    (
        'hour-before-reminders',
        'apps.notifications.tasks.send_hour_before_reminders',
        '*/5', '*', '*', '*', '*',
        'Every 5 min: nudge patients whose appointment starts in ~1 hour',
    ),
    (
        'confirmation-calls',
        'apps.notifications.tasks.make_confirmation_calls',
        '0', '10', '*', '*', '*',
        '10 AM IST automated confirmation calls (mocked currently)',
    ),
    (
        'retry-unanswered-calls',
        'apps.notifications.tasks.retry_unanswered_calls',
        '0', '14', '*', '*', '*',
        '2 PM IST retry of unanswered confirmation calls (mocked currently)',
    ),
]


class Command(BaseCommand):
    help = "Seed django-celery-beat with the project's periodic tasks (idempotent)."

    def handle(self, *args, **options):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        created, updated = 0, 0
        for name, task, minute, hour, dow, dom, moy, description in SCHEDULES:
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=minute,
                hour=hour,
                day_of_week=dow,
                day_of_month=dom,
                month_of_year=moy,
                timezone='Asia/Kolkata',
            )
            obj, was_created = PeriodicTask.objects.update_or_create(
                name=name,
                defaults={
                    'task': task,
                    'crontab': crontab,
                    'enabled': True,
                    'description': description,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(
                f"  {'+' if was_created else '~'} {name}  "
                f"({minute} {hour} {dom} {moy} {dow} IST)"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {created} created, {updated} updated.  "
            f"Edit at /admin/django_celery_beat/periodictask/"
        ))
