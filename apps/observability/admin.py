"""Bare-bones admin so logs are browseable immediately after Phase 1.
The polished list/detail/timeline UI comes in Phases 5-7."""
from django.contrib import admin
from django.utils.html import format_html

from apps.observability.models import LogEvent, LogEventArchive


_LEVEL_COLORS = {
    'debug':    ('#1f1f23', '#a1a1aa'),
    'info':     ('#1f1f23', '#a1a1aa'),
    'warn':     ('rgba(251,191,36,.14)',  '#fbbf24'),
    'error':    ('rgba(248,113,113,.14)', '#f87171'),
    'critical': ('rgba(248,113,113,.22)', '#f87171'),
}


def _level_pill(level: str) -> str:
    bg, fg = _LEVEL_COLORS.get(level, ('#1f1f23', '#a1a1aa'))
    return format_html(
        '<span style="background:{};color:{};padding:2px 9px;border-radius:999px;'
        'font:500 11px/1.4 ui-monospace,Menlo,monospace;">{}</span>',
        bg, fg, level.upper(),
    )


@admin.register(LogEvent)
class LogEventAdmin(admin.ModelAdmin):
    list_display  = ('created_at', 'level_pill', 'event', 'clinic',
                     'wa_masked', 'user_type', 'flow', 'step', 'message_short')
    list_filter   = ('level', 'event', 'user_type', 'flow', 'clinic')
    search_fields = ('event', 'message', 'whatsapp_number',
                     'trace_id', 'exc_type')
    readonly_fields = ('created_at', 'trace_id', 'level', 'event', 'source',
                       'clinic', 'whatsapp_number', 'user_type', 'flow', 'step',
                       'message', 'data', 'exc_type', 'exc_message',
                       'traceback', 'latency_ms')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 100

    # Logs are immutable. View only — no Add, no Save, no Delete in the row view.
    # Delete is allowed via the changelist for bulk cleanup.
    def has_add_permission(self, request):
        return False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        ctx = extra_context or {}
        # Hide Save / Save and continue / Delete on the detail page —
        # rows are immutable so the buttons would lie about the contract.
        ctx.update({
            'show_save': False,
            'show_save_and_continue': False,
            'show_save_and_add_another': False,
            'show_delete': False,
            'show_delete_link': False,
        })
        return super().change_view(request, object_id, form_url, extra_context=ctx)

    def level_pill(self, obj):
        return _level_pill(obj.level)
    level_pill.short_description = 'Level'

    def wa_masked(self, obj):
        if not obj.whatsapp_number:
            return ''
        n = obj.whatsapp_number
        return format_html(
            '<span style="font-family:ui-monospace,Menlo,monospace;">…{}</span>',
            n[-4:],
        )
    wa_masked.short_description = 'WhatsApp'

    def message_short(self, obj):
        return (obj.message or '')[:80]
    message_short.short_description = 'Message'


@admin.register(LogEventArchive)
class LogEventArchiveAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'level', 'event', 'whatsapp_number',
                    'clinic', 'message')
    search_fields = ('event', 'whatsapp_number', 'trace_id', 'exc_type')
    readonly_fields = ('created_at',)

    def has_add_permission(self, request):
        return False
