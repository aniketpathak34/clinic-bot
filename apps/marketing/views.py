from datetime import date

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.clinic.models import Appointment

from .models import DemoVideo, Lead


# Status auto-promotion ladder when a prospect opens their landing page.
# Page-open is a strong "they read the message" signal.
_ENGAGE_PROMOTE = {
    'new':         'replied',
    'sent':        'replied',
    # any further status (replied / demo_booked / pilot / not_interested /
    # invalid) is left alone — never downgrade engagement progress.
}

_BOT_UA_HINTS = (
    'bot', 'spider', 'crawler', 'preview', 'whatsapp', 'facebookexternal',
    'twitterbot', 'slackbot', 'discordbot', 'linkedinbot', 'telegrambot',
    'embedly', 'pingdom', 'monitor',
)


def _looks_like_bot(user_agent: str) -> bool:
    ua = (user_agent or '').lower()
    return any(h in ua for h in _BOT_UA_HINTS)


@require_GET
def landing(request):
    """Marketing home page.

    If a prospect lands here from their personalised page (`?from=<slug>`)
    we bump their visit counter — useful signal that they're exploring the
    full product, not just their pitch.
    """
    from_slug = request.GET.get('from', '').strip()
    if from_slug and not _looks_like_bot(request.META.get('HTTP_USER_AGENT', '')):
        try:
            lead = Lead.objects.get(slug=from_slug)
            now = timezone.now()
            lead.last_visited_at = now
            lead.visit_count = (lead.visit_count or 0) + 1
            update_fields = ['last_visited_at', 'visit_count']
            if not lead.engaged_at:
                lead.engaged_at = now
                update_fields.append('engaged_at')
            lead.save(update_fields=update_fields)
        except Lead.DoesNotExist:
            pass

    videos = {
        'patient': list(DemoVideo.objects.filter(role='patient', is_active=True)),
        'provider': list(DemoVideo.objects.filter(role='provider', is_active=True)),
        'other': list(DemoVideo.objects.filter(role='other', is_active=True)),
    }
    User = get_user_model()
    site_user = (
        User.objects.filter(is_superuser=True)
        .exclude(bot_number='', contact_number='')
        .order_by('id')
        .first()
    ) or User.objects.filter(is_superuser=True).order_by('id').first()
    bot_number = site_user.clean_bot_number if site_user else ''
    contact_number = site_user.clean_contact_number if site_user else ''
    contact_name = site_user.landing_display_name if site_user else 'us'
    today_bookings = max(
        Appointment.objects.filter(status='booked', slot__date=date.today()).count(),
        3,
    )
    return render(request, 'marketing/landing.html', {
        'videos': videos,
        'bot_number': bot_number,
        'contact_number': contact_number,
        'contact_name': contact_name,
        'today_bookings': today_bookings,
    })


# ────────────────────────────────────────────────────────────────
# Public legal pages — required for Meta App "Live" mode
# ────────────────────────────────────────────────────────────────

@require_GET
def brand_preview(request):
    """Internal logo concepts preview — not linked from anywhere public."""
    return render(request, 'marketing/brand_preview.html')


@require_GET
def privacy(request):
    return render(request, 'marketing/privacy.html')


@require_GET
def terms(request):
    return render(request, 'marketing/terms.html')


@require_GET
def data_deletion(request):
    return render(request, 'marketing/data_deletion.html')


# ────────────────────────────────────────────────────────────────
# Personalised outreach landing page
# ────────────────────────────────────────────────────────────────

@require_GET
def lead_landing(request, slug: str):
    """Per-prospect landing page reached from the WhatsApp outreach link.

    Records a visit, auto-promotes the lead's pipeline status the first time
    a real human opens it, and renders a hyper-personalised pitch.
    """
    lead = get_object_or_404(Lead, slug=slug)

    is_bot = _looks_like_bot(request.META.get('HTTP_USER_AGENT', ''))
    if not is_bot:
        now = timezone.now()
        update_fields = ['last_visited_at', 'visit_count']
        lead.last_visited_at = now
        lead.visit_count = (lead.visit_count or 0) + 1
        if not lead.engaged_at:
            lead.engaged_at = now
            update_fields.append('engaged_at')
        promoted = _ENGAGE_PROMOTE.get(lead.status)
        if promoted:
            lead.status = promoted
            update_fields.append('status')
            if not lead.contacted_at:
                lead.contacted_at = now
                update_fields.append('contacted_at')
        lead.save(update_fields=update_fields)

    # Pull the operator's WA contact number off the same User row used by
    # the public landing page, so this page shows "Aniket | +91 ..." too.
    User = get_user_model()
    site_user = (
        User.objects.filter(is_superuser=True)
        .exclude(bot_number='', contact_number='')
        .order_by('id').first()
    ) or User.objects.filter(is_superuser=True).order_by('id').first()
    contact_number = site_user.clean_contact_number if site_user else ''
    contact_name = site_user.landing_display_name if site_user else 'Aniket'

    # Specialty-aware demo video (falls back to any provider video).
    demo = (DemoVideo.objects.filter(role='provider', is_active=True).first()
            or DemoVideo.objects.filter(is_active=True).first())

    return render(request, 'marketing/lead_landing.html', {
        'lead': lead,
        'contact_number': contact_number,
        'contact_name': contact_name,
        'demo': demo,
    })
