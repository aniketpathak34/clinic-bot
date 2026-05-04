from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('p/<slug:slug>/', views.lead_landing, name='lead_landing'),
    # Public legal pages — required for Meta App "Live" mode
    path('privacy/', views.privacy, name='privacy'),
    path('terms/', views.terms, name='terms'),
    path('data-deletion/', views.data_deletion, name='data_deletion'),
    # SEO — crawler discovery
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('sitemap.xml', views.sitemap_xml, name='sitemap_xml'),
    # PWA + push notifications — must live at the site root so the
    # service worker's scope covers the whole admin. /static/ won't do.
    path('manifest.json', views.pwa_manifest, name='pwa_manifest'),
    path('sw.js', views.service_worker, name='service_worker'),
]
