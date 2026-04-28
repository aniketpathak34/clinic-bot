from django.urls import path

from .views import cron_webhook

urlpatterns = [
    # /webhook/cron/<secret>/<task>/
    path('cron/<str:secret>/<str:task>/', cron_webhook, name='cron_webhook'),
]
