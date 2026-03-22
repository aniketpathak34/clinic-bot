from django.contrib import admin
from django.urls import path
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
]
