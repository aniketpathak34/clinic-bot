from django.db import migrations


def seed_default_row(apps, schema_editor):
    """Create the singleton SiteSettings row with reasonable defaults.

    Admin can edit these anytime via /admin/marketing/sitesettings/1/change/.
    """
    SiteSettings = apps.get_model('marketing', 'SiteSettings')
    SiteSettings.objects.update_or_create(
        pk=1,
        defaults={
            'bot_number': '15551773718',       # Meta WhatsApp test number
            'contact_number': '917030344210',  # owner's personal WhatsApp
            'contact_name': 'Aniket',
        },
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('marketing', '0002_sitesettings'),
    ]
    operations = [
        migrations.RunPython(seed_default_row, noop_reverse),
    ]
