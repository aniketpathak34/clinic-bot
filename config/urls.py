from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404
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


def _admin_decoy(request, *args, **kwargs):
    """Decoy for the public-guessable /admin/ path — return 404 so bot scanners
    that probe '/admin/' don't even know an admin exists. The real admin lives
    at settings.ADMIN_URL_PATH (env-configurable, non-guessable in production).
    """
    raise Http404("Not found")


urlpatterns = [
    # Real admin at the env-configured path (default: 'admin' for local dev).
    path(f'{settings.ADMIN_URL_PATH}/', admin.site.urls),
    path('api/', api.urls),
    # External-scheduler webhook (GitHub Actions cron, etc.) — see apps/notifications/views.py
    path('webhook/', include('apps.notifications.urls')),
    path('', include('apps.marketing.urls')),
]

# In production, if ADMIN_URL_PATH was changed away from 'admin', also serve a
# 404 decoy at /admin/ so bots can't even tell the framework. (Skip if the real
# admin still lives at /admin/ — i.e., local dev.)
if settings.ADMIN_URL_PATH != 'admin':
    urlpatterns.insert(1, path('admin/', _admin_decoy))
    urlpatterns.insert(2, path('admin/<path:rest>', _admin_decoy))

# Serve user-uploaded media.
#
# On Render free tier the filesystem is ephemeral and the dev-only static()
# helper is fine for pilot-scale traffic. For real production volume switch to
# S3 / Cloudinary / Render disk and remove the DEBUG check below.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
