from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('p/<slug:slug>/', views.lead_landing, name='lead_landing'),
    # Public legal pages — required for Meta App "Live" mode
    path('privacy/', views.privacy, name='privacy'),
    path('terms/', views.terms, name='terms'),
    path('data-deletion/', views.data_deletion, name='data_deletion'),
]
