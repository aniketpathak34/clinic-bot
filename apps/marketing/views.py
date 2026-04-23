from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.clinic.models import Clinic
from .models import DemoVideo


@require_GET
def landing(request):
    """Marketing home page — product overview, demo videos, pricing, CTA."""
    videos = {
        'patient': list(DemoVideo.objects.filter(role='patient', is_active=True)),
        'provider': list(DemoVideo.objects.filter(role='provider', is_active=True)),
        'other': list(DemoVideo.objects.filter(role='other', is_active=True)),
    }

    # Use the first active clinic with a WhatsApp number for the wa.me CTA.
    demo_clinic = (
        Clinic.objects.exclude(display_phone_number='')
        .exclude(display_phone_number__isnull=True)
        .order_by('created_at')
        .first()
    )
    wa_number = (demo_clinic.display_phone_number if demo_clinic else '').lstrip('+')

    return render(request, 'marketing/landing.html', {
        'videos': videos,
        'wa_number': wa_number,
        'clinic_name': demo_clinic.name if demo_clinic else 'Clinic Bot',
    })
