from django.db import migrations


DEMO_VIDEOS = [
    {
        'title': 'Patient Flow on WhatsApp',
        'role': 'patient',
        'description': 'How a patient books an appointment in 30 seconds — no app, no signup, just WhatsApp.',
        'embed_url': 'https://youtube.com/shorts/Fvt_8WAemZs',
        'order': 0,
        'is_active': True,
    },
    {
        'title': 'Doctor Flow on WhatsApp',
        'role': 'provider',
        'description': 'How a doctor sets availability and manages bookings from WhatsApp — no app, no login.',
        'embed_url': 'https://www.youtube.com/embed/evKBZgkVT8E',
        'order': 0,
        'is_active': True,
    },
]


def seed_videos(apps, schema_editor):
    DemoVideo = apps.get_model('marketing', 'DemoVideo')
    for v in DEMO_VIDEOS:
        DemoVideo.objects.update_or_create(
            role=v['role'],
            title=v['title'],
            defaults=v,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('marketing', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(seed_videos, noop_reverse),
    ]
