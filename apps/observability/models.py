"""LogEvent — structured event row written by `apps.observability.api.log`.

Every webhook, state transition, send attempt, error, and Celery task entry
emits one of these. Indexed for the three queries we care about:
  • "show me one user's full session"   →  whatsapp_number index
  • "show me one webhook end-to-end"     →  trace_id index
  • "show me everything broken today"    →  level index
"""
from django.db import models


LEVELS = [
    ('debug',    'Debug'),
    ('info',     'Info'),
    ('warn',     'Warning'),
    ('error',    'Error'),
    ('critical', 'Critical'),
]


class LogEventBase(models.Model):
    """Shared schema between hot table and archive table."""

    id              = models.BigAutoField(primary_key=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    # One per inbound webhook (or per Celery task run). Every downstream event
    # the bot emits for that message shares this ID, so a single grep / filter
    # gives you the whole story.
    trace_id        = models.CharField(max_length=16, blank=True)

    # What
    level           = models.CharField(max_length=10, choices=LEVELS, default='info')
    event           = models.CharField(max_length=64)
    # module:function  e.g. "conversations.engine:handle_message"
    source          = models.CharField(max_length=120, blank=True)

    # Correlation keys
    clinic          = models.ForeignKey(
        'clinic.Clinic', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    whatsapp_number = models.CharField(max_length=15, blank=True)
    user_type       = models.CharField(max_length=10, blank=True)

    # State-machine context
    flow            = models.CharField(max_length=40, blank=True)
    step            = models.CharField(max_length=40, blank=True)

    # Payload
    message         = models.TextField(blank=True)
    data            = models.JSONField(default=dict, blank=True)

    # Errors only — auto-filled by `log.error(..., exc=e)`
    exc_type        = models.CharField(max_length=80, blank=True)
    exc_message     = models.TextField(blank=True)
    traceback       = models.TextField(blank=True)

    # Performance — set by `log.span()` on close
    latency_ms      = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def __str__(self) -> str:
        bits = [self.created_at.strftime('%H:%M:%S'), self.level.upper(), self.event]
        if self.whatsapp_number:
            bits.append(f'wa={self.whatsapp_number[-10:]}')
        return ' '.join(bits)


class LogEvent(LogEventBase):
    """Hot table — last ~30 days. Heavily indexed."""

    class Meta:
        verbose_name = 'Log event'
        verbose_name_plural = 'Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'], name='le_created_idx'),
            models.Index(fields=['trace_id', 'created_at'], name='le_trace_idx'),
            models.Index(fields=['whatsapp_number', '-created_at'], name='le_wa_idx'),
            models.Index(fields=['clinic', '-created_at'], name='le_clinic_idx'),
            models.Index(fields=['level', '-created_at'], name='le_level_idx'),
            models.Index(fields=['event', '-created_at'], name='le_event_idx'),
        ]


class LogEventArchive(LogEventBase):
    """Cold table — rows moved here by the nightly retention task.
    No indexes (cheap storage); only consulted for after-the-fact deep dives."""

    class Meta:
        verbose_name = 'Archived log event'
        verbose_name_plural = 'Archived logs'
        ordering = ['-created_at']
