"""RequestLog — one row per inbound webhook (or per Celery task run).

The `events` JSONField holds the full ordered breadcrumb of what happened
during that request. The top-level columns are denormalized rollups so the
admin list can filter / sort / search without parsing JSON on every query.

Why one row per request, not one per event?
  • A clinic admin reads ONE row to understand what happened, not 4-5
  • Single INSERT per webhook → 5× less DB churn
  • events JSON keeps the full timeline for drill-down
  • Greppable in stdout regardless — see apps.observability.api._to_stdout
"""
from django.db import models


LEVELS = [
    ('debug',    'Debug'),
    ('info',     'Info'),
    ('warn',     'Warning'),
    ('error',    'Error'),
    ('critical', 'Critical'),
]

REQUEST_KINDS = [
    ('webhook', 'Webhook'),
    ('admin',   'Admin'),
    ('task',    'Celery task'),
    ('shell',   'Shell / management cmd'),
    ('other',   'Other'),
]


class RequestLog(models.Model):
    """One row = one inbound request, with the full event breadcrumb."""

    id              = models.BigAutoField(primary_key=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    trace_id        = models.CharField(max_length=16, blank=True)
    request_kind    = models.CharField(max_length=12, choices=REQUEST_KINDS,
                                       default='webhook')

    # Highest severity seen across all events in this request — used by the
    # admin filter so "show me all errors today" is a single column query.
    level           = models.CharField(max_length=10, choices=LEVELS, default='info')

    # Correlation — these are the values at the END of the request. If the
    # user_type was resolved mid-request, this is the resolved value.
    clinic          = models.ForeignKey(
        'clinic.Clinic', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    whatsapp_number = models.CharField(max_length=15, blank=True)
    user_type       = models.CharField(max_length=10, blank=True)

    # Last known flow/step at the end of the request
    final_flow      = models.CharField(max_length=40, blank=True)
    final_step      = models.CharField(max_length=40, blank=True)
    # Name of the most meaningful event (the LAST non-route_dispatched event)
    final_event     = models.CharField(max_length=64, blank=True)

    # What the user said + a one-line auto-summary of what the bot did
    inbound_text    = models.CharField(max_length=200, blank=True)
    summary         = models.TextField(blank=True)

    # Roll-ups
    event_count     = models.PositiveIntegerField(default=0)
    warn_count      = models.PositiveIntegerField(default=0)
    error_count     = models.PositiveIntegerField(default=0)

    # The full ordered timeline — each item is
    #   {ts, level, event, source, message, data, exc_type, exc_message, traceback}
    events          = models.JSONField(default=list, blank=True)

    # The first error encountered (if any) — promoted to top-level columns
    # so the admin can sort by exception type.
    exc_type        = models.CharField(max_length=80, blank=True)
    exc_message     = models.TextField(blank=True)
    traceback       = models.TextField(blank=True)

    # Wall-clock latency of the request
    latency_ms      = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = 'Request log'
        verbose_name_plural = 'Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'],                     name='rl_created_idx'),
            models.Index(fields=['trace_id'],                        name='rl_trace_idx'),
            models.Index(fields=['whatsapp_number', '-created_at'],  name='rl_wa_idx'),
            models.Index(fields=['clinic', '-created_at'],           name='rl_clinic_idx'),
            models.Index(fields=['level', '-created_at'],            name='rl_level_idx'),
            models.Index(fields=['final_event', '-created_at'],      name='rl_event_idx'),
        ]

    def __str__(self) -> str:
        bits = [self.created_at.strftime('%H:%M:%S'),
                self.level.upper(),
                self.final_event or '?',
                f'({self.event_count} events)']
        if self.whatsapp_number:
            bits.append(f'wa=…{self.whatsapp_number[-4:]}')
        return ' '.join(bits)
