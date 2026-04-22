from django.apps import AppConfig


class ClinicConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clinic'

    def ready(self):
        from apps.clinic import signals  # noqa: F401
