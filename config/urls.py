from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from ninja import NinjaAPI

from apps.whatsapp.views import router as webhook_router
from apps.whatsapp.test_views import router as test_router

api = NinjaAPI(
    title="WhatsApp Clinic Bot API",
    version="1.0.0",
    docs_url="/docs",
)

api.add_router("/webhook", webhook_router, tags=["Webhook"])
api.add_router("/test", test_router, tags=["Test/Dev"])

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('', include('apps.marketing.urls')),
]

# Serve uploaded media via the dev server (in prod, whitenoise handles it).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
