from django.contrib import admin

from .models import Payment, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'clinic', 'tier', 'status', 'monthly_amount_inr',
        'started_at', 'current_period_end', 'pilot_ends_at',
    )
    list_filter = ('status', 'tier')
    search_fields = ('clinic__name', 'clinic__clinic_code')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('clinic',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'subscription', 'amount_inr', 'method',
        'reference', 'paid_at', 'marked_by',
    )
    list_filter = ('method', 'paid_at')
    search_fields = (
        'subscription__clinic__name',
        'subscription__clinic__clinic_code',
        'reference',
    )
    readonly_fields = ('paid_at', 'created_at', 'marked_by')
    autocomplete_fields = ('subscription',)
