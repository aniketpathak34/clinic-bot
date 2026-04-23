from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import DemoVideo


@require_GET
def landing(request):
    """Marketing home page — product overview, demo videos, pricing, CTAs.

    Both WhatsApp numbers come from the first superuser's User row
    (edit at /admin/accounts/user/{id}/change/ under "Landing page contacts").
    """
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

    return render(request, 'marketing/landing.html', {
        'videos': videos,
        'bot_number': bot_number,
        'contact_number': contact_number,
        'contact_name': contact_name,
    })
