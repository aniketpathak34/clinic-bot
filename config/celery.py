import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('clinic_bot')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Morning: Make confirmation calls for tomorrow's appointments
    'confirmation-calls': {
        'task': 'apps.notifications.tasks.make_confirmation_calls',
        'schedule': crontab(hour=10, minute=0),  # 10 AM IST
    },
    # Afternoon: Retry unanswered calls
    'retry-unanswered-calls': {
        'task': 'apps.notifications.tasks.retry_unanswered_calls',
        'schedule': crontab(hour=14, minute=0),  # 2 PM IST
    },
    # Evening: Send WhatsApp reminders for tomorrow's appointments
    'day-before-reminders': {
        'task': 'apps.notifications.tasks.send_day_before_reminders',
        'schedule': crontab(hour=18, minute=0),  # 6 PM IST
    },
    # Every 5 minutes: nudge patients whose appointment starts in ~1 hour
    'hour-before-reminders': {
        'task': 'apps.notifications.tasks.send_hour_before_reminders',
        'schedule': crontab(minute='*/5'),
    },
    # Every morning at 9 AM IST: fetch 20 fresh clinic leads via Google Places API
    'daily-lead-generation': {
        'task': 'apps.notifications.tasks.fetch_daily_leads',
        'schedule': crontab(hour=9, minute=0),
    },
}
