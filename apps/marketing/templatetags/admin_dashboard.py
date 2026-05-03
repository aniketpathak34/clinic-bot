"""Template tags powering the redesigned admin sidebar.

Provides:
  • {% sidebar_counts as counts %} — live numbers for badges next to each link.
  • {% todays_mission as mission %} — up to 3 priority cards based on
    time-of-day and current pipeline state.

Lightweight: all queries run inside a single small QuerySet pass per page
load. No Redis / cache layer needed.
"""
from __future__ import annotations

from datetime import date, timedelta

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

register = template.Library()


def _safe_url(view_name: str, *args, **kwargs) -> str:
    try:
        return reverse(view_name, args=args, kwargs=kwargs)
    except NoReverseMatch:
        return '#'


@register.simple_tag
def sidebar_counts() -> dict:
    """One ORM-light pass that returns every badge number the sidebar needs.

    Returns 0 for everything if any model is unavailable — keeps the sidebar
    rendering even if an app is in a partial-migration state.
    """
    out = {
        'leads_total': 0, 'leads_hot': 0, 'leads_medium': 0,
        'leads_followup_due': 0, 'leads_demo_booked': 0,
        'leads_engaged_now': 0, 'leads_new_today': 0,
        'appts_today': 0, 'appts_next_hour': 0, 'appts_tomorrow': 0,
        'slots_unbooked': 0, 'patients_total': 0, 'doctors_total': 0,
        'call_logs_today': 0, 'demo_videos_active': 0,
    }
    now = timezone.now()
    today = now.date()
    hour_ago = now - timedelta(hours=1)
    next_hour = now + timedelta(hours=1)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        from apps.marketing.models import Lead, DemoVideo
        leads = Lead.objects.all()
        out['leads_total'] = leads.count()
        out['leads_demo_booked'] = leads.filter(status='demo_booked').count()
        out['leads_engaged_now'] = leads.filter(last_visited_at__gte=hour_ago).count()
        out['leads_new_today'] = leads.filter(created_at__date=today).count()
        # Walking the queryset for followup_status() is acceptable —
        # ~hundreds of rows, and we're already on an admin page that
        # tolerates that load.
        hot = medium = due = 0
        for lead in leads.iterator():
            action = lead.followup_status()
            if not action:
                continue
            due += 1
            if action.get('urgency') == 'hot':
                hot += 1
            elif action.get('urgency') == 'medium':
                medium += 1
        out['leads_hot'] = hot
        out['leads_medium'] = medium
        out['leads_followup_due'] = due
        out['demo_videos_active'] = DemoVideo.objects.filter(is_active=True).count()
    except Exception:
        pass

    try:
        from apps.clinic.models import Appointment, AvailableSlot, Patient, Doctor
        out['appts_today'] = Appointment.objects.filter(
            slot__date=today, status='booked'
        ).count()
        out['appts_next_hour'] = Appointment.objects.filter(
            slot__date=today,
            slot__time__gte=now.time(),
            slot__time__lt=next_hour.time(),
            status='booked',
        ).count()
        out['appts_tomorrow'] = Appointment.objects.filter(
            slot__date=today + timedelta(days=1), status='booked'
        ).count()
        out['slots_unbooked'] = AvailableSlot.objects.filter(
            date__gte=today, is_booked=False
        ).count()
        out['patients_total'] = Patient.objects.count()
        out['doctors_total'] = Doctor.objects.count()
    except Exception:
        pass

    try:
        from apps.notifications.models import CallLog
        out['call_logs_today'] = CallLog.objects.filter(
            created_at__gte=day_start
        ).count()
    except Exception:
        pass

    return out


@register.simple_tag
def todays_mission() -> list:
    """Up to 3 priority cards for the top of the sidebar.

    Selection is rule-based: most urgent first. We always return a list,
    possibly empty — the template hides the panel if so.
    """
    counts = sidebar_counts()
    hour = timezone.localtime().hour
    cards = []

    # 1) Hot leads — highest priority, always shown if any
    if counts['leads_hot']:
        cards.append({
            'tone': 'hot',
            'emoji': '🔥',
            'title': f"{counts['leads_hot']} hot lead{'s' if counts['leads_hot'] != 1 else ''}",
            'sub': 'opened your page, ready to close',
            'href': _safe_url('admin:marketing_lead_changelist') + '?needs_followup=1',
        })

    # 2) Demo happening today
    if counts['leads_demo_booked']:
        cards.append({
            'tone': 'amber',
            'emoji': '📅',
            'title': f"{counts['leads_demo_booked']} demo{'s' if counts['leads_demo_booked'] != 1 else ''} booked",
            'sub': 'prep talking points',
            'href': _safe_url('admin:marketing_lead_changelist') + '?status__exact=demo_booked',
        })

    # 3) Follow-ups due — only if no hot already shown to keep panel focused
    if counts['leads_followup_due'] and not counts['leads_hot']:
        cards.append({
            'tone': 'cyan',
            'emoji': '📲',
            'title': f"{counts['leads_followup_due']} follow-up{'s' if counts['leads_followup_due'] != 1 else ''} due",
            'sub': 'send the WhatsApp template',
            'href': _safe_url('admin:marketing_lead_changelist') + '?needs_followup=1',
        })

    # 4) Patients in the next hour — operational urgency
    if counts['appts_next_hour']:
        cards.append({
            'tone': 'amber',
            'emoji': '⏰',
            'title': f"{counts['appts_next_hour']} appointment{'s' if counts['appts_next_hour'] != 1 else ''} in the next hour",
            'sub': "check today's schedule",
            'href': _safe_url('admin:clinic_appointment_changelist'),
        })

    # 5) Engaged-right-now — visiting their page in real time
    if counts['leads_engaged_now']:
        cards.append({
            'tone': 'cyan',
            'emoji': '👀',
            'title': f"{counts['leads_engaged_now']} watching their page now",
            'sub': 'strike while warm',
            'href': _safe_url('admin:marketing_lead_changelist') + '?engaged=1',
        })

    # Time-aware fillers — only if we still have room
    if len(cards) < 3:
        if 6 <= hour < 12 and counts['leads_new_today']:
            cards.append({
                'tone': 'cyan', 'emoji': '🌅',
                'title': f"{counts['leads_new_today']} fresh leads today",
                'sub': 'morning push window',
                'href': _safe_url('admin:marketing_lead_changelist'),
            })
        elif 18 <= hour < 23 and counts['appts_tomorrow']:
            cards.append({
                'tone': 'amber', 'emoji': '🌙',
                'title': f"{counts['appts_tomorrow']} appointments tomorrow",
                'sub': 'confirm reminders',
                'href': _safe_url('admin:clinic_appointment_changelist'),
            })

    # Final fallback — keep the panel from feeling dead
    if not cards:
        cards.append({
            'tone': 'dim', 'emoji': '✨',
            'title': "All caught up",
            'sub': 'work on the product',
            'href': _safe_url('admin:marketing_lead_changelist'),
        })

    return cards[:3]


@register.simple_tag
def admin_url(name: str, *args) -> str:
    """Shortcut: {% admin_url 'admin:marketing_lead_changelist' %}."""
    return _safe_url(name, *args)


@register.simple_tag
def header_signals() -> dict:
    """Cheap, runs on every admin page render. Used by the global header
    strip for instant first-paint values; JS later refreshes via fetch."""
    from datetime import timedelta
    from django.utils import timezone
    try:
        from apps.marketing.models import Lead
        now = timezone.now()
        today = now.date()
        hour_ago = now - timedelta(hours=1)
        return {
            'hot_now': Lead.objects.filter(last_visited_at__gte=hour_ago).count(),
            'sent_today': Lead.objects.filter(contacted_at__date=today).count(),
            'time_str': timezone.localtime().strftime('%I:%M %p').lstrip('0'),
        }
    except Exception:
        return {'hot_now': 0, 'sent_today': 0, 'time_str': ''}


@register.simple_tag
def war_room_metrics() -> dict:
    """Wraps dashboard.dashboard_metrics() so the admin index template can pull
    every number it needs in a single tag call."""
    try:
        from apps.marketing.dashboard import dashboard_metrics
        return dashboard_metrics()
    except Exception:
        return {
            'pipeline_value': 0, 'pipeline_value_inr_short': '₹0',
            'funnel': [], 'sparkline_14d': [],
            'next_moves': [], 'kpis': {},
        }
