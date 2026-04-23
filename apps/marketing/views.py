from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import DemoVideo, SiteSettings


@require_GET
def landing(request):
    """Marketing home page — product overview, demo videos, pricing, CTAs.

    Both WhatsApp numbers come from the SiteSettings singleton (editable in
    /admin/marketing/sitesettings/) — not env vars, not the Clinic table.
    """
    videos = {
        'patient': list(DemoVideo.objects.filter(role='patient', is_active=True)),
        'provider': list(DemoVideo.objects.filter(role='provider', is_active=True)),
        'other': list(DemoVideo.objects.filter(role='other', is_active=True)),
    }

    site = SiteSettings.get()
    return render(request, 'marketing/landing.html', {
        'videos': videos,
        'bot_number': site.clean_bot_number,
        'contact_number': site.clean_contact_number,
        'contact_name': site.contact_name,
    })
