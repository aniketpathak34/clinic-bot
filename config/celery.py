import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('clinic_bot')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Periodic tasks are now stored in the database via django_celery_beat.
# Manage them at /admin/django_celery_beat/periodictask/
#
# Initial schedule is seeded by:
#     python manage.py setup_periodic_tasks
# (called automatically by build.sh on every Render deploy)
#
# Reference of what gets seeded — keep in sync with the management command:
#   • daily-lead-generation   crontab(0 9 * * *)   IST  → fetch_daily_leads
#   • day-before-reminders    crontab(0 18 * * *)  IST  → send_day_before_reminders
#   • hour-before-reminders   crontab(*/5 * * * *) IST  → send_hour_before_reminders
#   • confirmation-calls      crontab(0 10 * * *)  IST  → make_confirmation_calls
#   • retry-unanswered-calls  crontab(0 14 * * *)  IST  → retry_unanswered_calls
