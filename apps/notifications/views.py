"""Cron webhook — lets external schedulers (GitHub Actions, cron-job.org, …)
trigger our scheduled tasks via a secret-protected URL.

URL pattern: /webhook/cron/<secret>/<task>/

Why this exists: Render's free tier no longer offers background workers, so
we can't run Celery beat + worker. Instead, an external scheduler hits these
URLs and the task runs synchronously inside the web service. Free, reliable,
no extra services.

Example:
    POST /webhook/cron/abc123xyz789/fetch_daily_leads/
    → {"ok": true, "ran": "fetch_daily_leads", "duration_ms": 2150, "result": null}

The <secret> path component must match the CRON_SECRET env var. Wrong secret
returns 403. Bad task name returns 404.
"""
import logging
import time

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.notifications import tasks as task_module

logger = logging.getLogger(__name__)


# Whitelist of tasks the webhook is allowed to invoke. Adding a new task means
# adding it here explicitly — defence-in-depth so a leaked secret can't run
# arbitrary functions in apps.notifications.tasks.
ALLOWED_TASKS = {
    'fetch_daily_leads',
    'send_day_before_reminders',
    'send_hour_before_reminders',
    'make_confirmation_calls',
    'retry_unanswered_calls',
    'generate_monthly_slots',
}


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def cron_webhook(request, secret: str, task: str):
    expected = getattr(settings, 'CRON_SECRET', '')
    if not expected:
        return JsonResponse(
            {'ok': False, 'error': 'CRON_SECRET not configured on the server'},
            status=503,
        )
    if secret != expected:
        logger.warning("[cron] Bad secret for task=%s from %s", task, request.META.get('REMOTE_ADDR'))
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    if task not in ALLOWED_TASKS:
        return JsonResponse(
            {'ok': False, 'error': f'unknown task. allowed: {sorted(ALLOWED_TASKS)}'},
            status=404,
        )

    fn = getattr(task_module, task, None)
    if fn is None:
        return JsonResponse({'ok': False, 'error': f'task function {task} not found'}, status=404)

    started = time.monotonic()
    try:
        # Tasks are @shared_task decorated but plain Python under the hood —
        # call directly, synchronously. Skip Celery entirely.
        result = fn() if not hasattr(fn, 'run') else fn.run()
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info("[cron] %s completed in %dms (result=%r)", task, duration_ms, result)
        return JsonResponse({
            'ok': True,
            'ran': task,
            'duration_ms': duration_ms,
            'result': result if isinstance(result, (str, int, float, bool, type(None))) else str(result),
        })
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.exception("[cron] %s failed after %dms", task, duration_ms)
        return JsonResponse({
            'ok': False,
            'ran': task,
            'duration_ms': duration_ms,
            'error': str(exc),
        }, status=500)
