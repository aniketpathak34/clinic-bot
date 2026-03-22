from django.contrib import admin
from .models import ConversationState


@admin.register(ConversationState)
class ConversationStateAdmin(admin.ModelAdmin):
    list_display = ('whatsapp_number', 'user_type', 'clinic', 'current_flow', 'step', 'language', 'updated_at')
    list_filter = ('user_type', 'current_flow', 'clinic')
    search_fields = ('whatsapp_number',)
