from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('p/<slug:slug>/', views.lead_landing, name='lead_landing'),
]
