from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from ninja import NinjaAPI

from apps.whatsapp.views import router as webhook_router
from apps.whatsapp.test_views import router as test_router

api = NinjaAPI(
    title="DocPing API",
    version="1.0.0",
    docs_url="/docs",
)

# Brand the Django admin so reviewers and operators see "DocPing" everywhere.
admin.site.site_header = "DocPing admin"
admin.site.site_title = "DocPing"
admin.site.index_title = "Operations"

api.add_router("/webhook", webhook_router, tags=["Webhook"])
api.add_router("/test", test_router, tags=["Test/Dev"])

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    # External-scheduler webhook (GitHub Actions cron, etc.) — see apps/notifications/views.py
    path('webhook/', include('apps.notifications.urls')),
    path('', include('apps.marketing.urls')),
]

# Serve user-uploaded media.
#
# On Render free tier the filesystem is ephemeral and the dev-only static()
# helper is fine for pilot-scale traffic. For real production volume switch to
# S3 / Cloudinary / Render disk and remove the DEBUG check below.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
