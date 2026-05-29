"""RequestLog admin — one row per webhook, events visible as a timeline."""
import json
from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.observability.models import RequestLog


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


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display  = ('created_at', 'level_pill', 'final_event_short',
                     'clinic', 'wa_masked', 'user_type', 'final_flow',
                     'event_count_pill', 'inbound_text_short', 'latency_lbl')
    list_filter   = ('level', 'user_type', 'final_flow', 'request_kind', 'clinic')
    search_fields = ('final_event', 'summary', 'whatsapp_number',
                     'trace_id', 'exc_type', 'inbound_text')
    readonly_fields = ('created_at', 'trace_id', 'request_kind', 'level',
                       'clinic', 'whatsapp_number', 'user_type',
                       'final_flow', 'final_step', 'final_event',
                       'inbound_text', 'summary',
                       'event_count', 'warn_count', 'error_count',
                       'events_pretty',
                       'exc_type', 'exc_message', 'traceback',
                       'latency_ms')
    exclude = ('events',)   # show pretty rendition instead
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'
    list_per_page = 50

    fieldsets = (
        ('Overview', {
            'fields': ('created_at', 'level', 'request_kind', 'trace_id',
                       'latency_ms', 'summary'),
        }),
        ('Who & where', {
            'fields': ('clinic', 'whatsapp_number', 'user_type',
                       'final_flow', 'final_step', 'final_event'),
        }),
        ('Inbound message', {
            'fields': ('inbound_text',),
        }),
        ('Counts', {
            'fields': ('event_count', 'warn_count', 'error_count'),
        }),
        ('Event timeline', {
            'fields': ('events_pretty',),
        }),
        ('Error details', {
            'classes': ('collapse',),
            'fields': ('exc_type', 'exc_message', 'traceback'),
        }),
    )

    def has_add_permission(self, request):
        return False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        ctx = extra_context or {}
        ctx.update({
            'show_save': False,
            'show_save_and_continue': False,
            'show_save_and_add_another': False,
            'show_delete': False,
            'show_delete_link': False,
        })
        return super().change_view(request, object_id, form_url, extra_context=ctx)

    # ─── List-cell formatters ────────────────────────────────────
    def level_pill(self, obj):
        return _level_pill(obj.level)
    level_pill.short_description = 'Level'
    level_pill.admin_order_field = 'level'

    def wa_masked(self, obj):
        if not obj.whatsapp_number:
            return ''
        return format_html(
            '<span style="font-family:ui-monospace,Menlo,monospace;">…{}</span>',
            obj.whatsapp_number[-4:],
        )
    wa_masked.short_description = 'WhatsApp'

    def event_count_pill(self, obj):
        bg = '#1f1f23'
        fg = '#a1a1aa'
        if obj.error_count:   bg, fg = 'rgba(248,113,113,.14)', '#f87171'
        elif obj.warn_count:  bg, fg = 'rgba(251,191,36,.14)', '#fbbf24'
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:999px;'
            'font:500 11px/1.4 ui-monospace,Menlo,monospace;" title="info/warn/error">'
            '{}</span>',
            bg, fg, obj.event_count,
        )
    event_count_pill.short_description = 'Events'
    event_count_pill.admin_order_field = 'event_count'

    def final_event_short(self, obj):
        return obj.final_event or '—'
    final_event_short.short_description = 'Final event'
    final_event_short.admin_order_field = 'final_event'

    def inbound_text_short(self, obj):
        s = obj.inbound_text or ''
        return s[:50] + ('…' if len(s) > 50 else '')
    inbound_text_short.short_description = 'Inbound'

    def latency_lbl(self, obj):
        if obj.latency_ms is None:
            return ''
        return f'{obj.latency_ms} ms'
    latency_lbl.short_description = 'Latency'
    latency_lbl.admin_order_field = 'latency_ms'

    # ─── Detail-page events timeline ─────────────────────────────
    def events_pretty(self, obj):
        if not obj.events:
            return '—'
        rows = []
        for i, e in enumerate(obj.events):
            level = e.get('level', 'info')
            lvl_bg, lvl_fg = _LEVEL_COLORS.get(level, ('#1f1f23', '#a1a1aa'))
            name = e.get('event', '?')
            msg = e.get('message') or ''
            src = e.get('source') or ''
            flow = e.get('flow') or ''
            step = e.get('step') or ''
            data = e.get('data') or {}
            data_str = json.dumps(data, default=str) if data else ''
            exc = e.get('exc_type') or ''
            rows.append(
                f'<tr style="border-top:1px solid #232327;">'
                f'  <td style="padding:6px 10px;color:#71717a;font:500 11px/1.3 ui-monospace,Menlo,monospace;'
                f'             white-space:nowrap;vertical-align:top;">{i+1:>2}.</td>'
                f'  <td style="padding:6px 10px;vertical-align:top;">'
                f'    <span style="background:{lvl_bg};color:{lvl_fg};padding:1px 7px;border-radius:999px;'
                f'                 font:500 10px/1.4 ui-monospace,Menlo,monospace;">{level.upper()}</span>'
                f'  </td>'
                f'  <td style="padding:6px 10px;color:#fafafa;font:500 12.5px/1.3 ui-monospace,Menlo,monospace;'
                f'             white-space:nowrap;vertical-align:top;">{name}</td>'
                f'  <td style="padding:6px 10px;color:#a1a1aa;font-size:12px;vertical-align:top;">'
                f'    {msg or ""}<br>'
                f'    <span style="color:#52525b;font-size:11px;font-family:ui-monospace,Menlo,monospace;">'
                f'      {flow}{"/" if flow and step else ""}{step}{" · " if (flow or step) and data_str else ""}{data_str}'
                f'      {(" · " + exc) if exc else ""}'
                f'    </span>'
                f'    <span style="color:#52525b;font-size:10.5px;font-family:ui-monospace,Menlo,monospace;'
                f'                 display:block;margin-top:3px;">{src}</span>'
                f'  </td>'
                f'</tr>'
            )
        html = (
            f'<table style="border-collapse:collapse;background:#131316;'
            f'border:1px solid #232327;border-radius:8px;overflow:hidden;width:100%;">'
            f'{"".join(rows)}</table>'
        )
        return mark_safe(html)
    events_pretty.short_description = 'Events'
