from datetime import date

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_safe

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


# ────────────────────────────────────────────────────────────────
# SEO — robots.txt and sitemap.xml served as plain endpoints
# ────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────
# PWA — manifest.json + service worker (must live at the site root
# so the SW's scope covers the whole admin)
# ────────────────────────────────────────────────────────────────

@require_safe
def pwa_manifest(request):
    """Return the PWA manifest as JSON. Browsers fetch this when deciding
    if a site is installable to the home screen."""
    from django.http import JsonResponse
    return JsonResponse({
        'name': 'DocPing — Ops Console',
        'short_name': 'DocPing',
        'description': 'WhatsApp-based clinic appointment booking — operator dashboard',
        'start_url': '/admin/',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0a0a0f',
        'theme_color': '#0a0a0f',
        'icons': [
            {'src': '/static/marketing/brand/docping-icon.svg',
             'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any'},
            {'src': '/static/marketing/brand/docping-icon.svg',
             'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'maskable'},
        ],
    })


@require_safe
def service_worker(request):
    """Service worker — must be served from /sw.js (root scope) and with a
    JS content type. The body is small: register push handler + click handler."""
    from django.http import HttpResponse
    body = """// DocPing service worker — handles web push notifications.
// Cache: nothing (we don't do offline; this SW only exists for push).
self.addEventListener('install', function (e) { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });

self.addEventListener('push', function (event) {
  if (!event.data) return;
  var payload = {};
  try { payload = event.data.json(); } catch (e) { payload = { title: 'DocPing', body: event.data.text() }; }
  var title = payload.title || 'DocPing';
  var opts = {
    body: payload.body || '',
    icon: payload.icon || '/static/marketing/brand/docping-icon.svg',
    badge: payload.badge || '/static/marketing/brand/docping-icon.svg',
    tag: payload.tag || 'docping',
    renotify: true,
    requireInteraction: false,
    data: { url: payload.url || '/admin/' },
    vibrate: [60, 30, 60],
  };
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = (event.notification.data && event.notification.data.url) || '/admin/';
  event.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (winList) {
    for (var i = 0; i < winList.length; i++) {
      var c = winList[i];
      if (c.url.indexOf(self.registration.scope) === 0 && 'focus' in c) {
        c.focus();
        if ('navigate' in c) c.navigate(url);
        return;
      }
    }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});
"""
    resp = HttpResponse(body, content_type='application/javascript; charset=utf-8')
    # Allow the SW to control the entire site root.
    resp['Service-Worker-Allowed'] = '/'
    return resp


@require_safe  # Allows both GET and HEAD — search-engine crawlers often probe with HEAD first
def robots_txt(request):
    """Serve /robots.txt — tells crawlers what to index and where to find sitemap."""
    from django.http import HttpResponse
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /webhook/\n"
        "Disallow: /api/\n"
        "Disallow: /p/\n"
        "Disallow: /brand/\n"
        "\n"
        "Sitemap: https://docping.in/sitemap.xml\n"
    )
    return HttpResponse(body, content_type='text/plain; charset=utf-8')


@require_safe  # Allows both GET and HEAD — Google Search Console probes with HEAD first
def sitemap_xml(request):
    """Serve /sitemap.xml listing the public pages we want Google to crawl."""
    from django.http import HttpResponse
    today = date.today().isoformat()
    pages = [
        ('https://docping.in/',                '1.0', 'weekly'),
        ('https://docping.in/privacy/',        '0.5', 'monthly'),
        ('https://docping.in/terms/',          '0.5', 'monthly'),
        ('https://docping.in/data-deletion/',  '0.3', 'monthly'),
    ]
    urls = '\n'.join(
        f'  <url>\n'
        f'    <loc>{url}</loc>\n'
        f'    <lastmod>{today}</lastmod>\n'
        f'    <changefreq>{freq}</changefreq>\n'
        f'    <priority>{prio}</priority>\n'
        f'  </url>'
        for url, prio, freq in pages
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{urls}\n'
        '</urlset>\n'
    )
    return HttpResponse(body, content_type='application/xml; charset=utf-8')


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
        was_first_visit = (lead.visit_count == 1)
        lead.save(update_fields=update_fields)

        # ── Hot-lead push: notify staff that a clinic is on their page now.
        # We push for every visit (not just first) because revisits are also
        # buying signal — but the title text differs so the operator knows.
        try:
            from .push import notify_all_staff
            notify_all_staff(
                title=("🔥 " + lead.name + " is on their page" if was_first_visit
                       else "👀 " + lead.name + " came back"),
                body=(f"First open · score {lead.score} · tap to open the lead drawer"
                      if was_first_visit else
                      f"Visit #{lead.visit_count} · {timezone.localtime(now).strftime('%I:%M %p').lstrip('0')}"),
                url=f"/admin/marketing/lead/?_drawer={lead.pk}",
                tag=f"docping-engaged-{lead.pk}",
            )
        except Exception:
            # Push failures must never break the lead's page render.
            import logging
            logging.getLogger(__name__).exception("hot-lead push failed")

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
