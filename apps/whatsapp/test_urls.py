from django.urls import path
from . import test_views

urlpatterns = [
    path('send/', test_views.test_send_message, name='test_send'),
    path('messages/', test_views.test_get_messages, name='test_messages'),
    path('conversation/<str:phone>/', test_views.test_conversation_state, name='test_conversation'),
    path('clear/', test_views.test_clear_messages, name='test_clear'),
]
