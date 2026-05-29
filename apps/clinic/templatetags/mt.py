"""Template filters for the MessageTemplate admin UI."""
import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name='mt_body')
def mt_body(value, max_chars=200):
    """Escape body + wrap {{n}} as variable pills + trim to max_chars."""
    if not value:
        return ''
    s = str(value)
    truncated = False
    if len(s) > max_chars:
        s = s[:max_chars].rstrip()
        truncated = True
    s = escape(s)
    s = re.sub(r'\{\{(\d+)\}\}',
               r'<span class="mt-var">{{\1}}</span>', s)
    if truncated:
        s += '…'
    return mark_safe(s)


@register.filter(name='mt_var_count')
def mt_var_count(value):
    """Count {{n}} variables in body."""
    if not value:
        return 0
    return len(set(re.findall(r'\{\{(\d+)\}\}', str(value))))


@register.filter(name='mt_needs_attention')
def mt_needs_attention(tpl):
    """True if rejected OR (not generic AND no clinics linked)."""
    if tpl.status == 'rejected':
        return True
    if not tpl.is_generic and not tpl.clinics.exists():
        return True
    return False


@register.filter(name='mt_scope_label')
def mt_scope_label(tpl):
    if tpl.is_generic:
        return 'All clinics'
    n = tpl.clinics.count()
    if n == 0:
        return 'No clinics'
    return f'{n} clinic{"" if n == 1 else "s"}'


@register.filter(name='mt_timestamp')
def mt_timestamp(dt):
    """Return seconds-since-epoch for sort (used as data attribute)."""
    if not dt:
        return 0
    return int(dt.timestamp())
