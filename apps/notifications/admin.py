from django.contrib import admin
from .models import CallLog


@admin.register(CallLog)
class CallLogAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'appointment', 'status', 'attempt_number', 'created_at')
    list_filter = ('status', 'attempt_number')
    search_fields = ('phone_number',)
