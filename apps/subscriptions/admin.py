from datetime import date, timedelta

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Payment, Subscription


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('paid_at', 'marked_by', 'created_at')
    fields = ('paid_at', 'amount_inr', 'method', 'reference', 'notes', 'marked_by')
    ordering = ('-paid_at',)
    can_delete = False


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):

    change_form_template = (
        'admin/subscriptions/subscription/change_form.html'
    )

    list_display = (
        'clinic_link', 'tier_pill', 'status_pill',
        'days_display', 'amount_display', 'payment_count',
    )
    list_filter  = ('status', 'tier')
    search_fields = ('clinic__name', 'clinic__clinic_code')
    readonly_fields = ('created_at', 'updated_at', 'days_until_expiry')
    inlines = [PaymentInline]

    fieldsets = (
        ('Clinic', {
            'fields': ('clinic',),
        }),
        ('Plan', {
            'fields': ('tier', 'status', 'monthly_amount_inr'),
            'description': (
                "Change tier here. Status transitions happen automatically "
                "via the daily check_subscription_status task, or manually "
                "via the Mark as Paid button."
            ),
        }),
        ('Dates', {
            'fields': (
                'started_at', 'current_period_end',
                'pilot_ends_at', 'days_until_expiry',
            ),
        }),
        ('Limits (future enforcement — leave blank = unlimited)', {
            'fields': ('doctors_limit', 'monthly_conversation_limit'),
            'classes': ('collapse',),
        }),
        ('Notes', {
            'fields': ('notes',),
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ── Custom URLs ──────────────────────────────────────────
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:pk>/mark-paid/',
                self.admin_site.admin_view(self.mark_paid_view),
                name='subscriptions_subscription_mark_paid',
            ),
        ]
        return custom + urls

    # ── Mark as paid view ────────────────────────────────────
    def mark_paid_view(self, request, pk):
        sub = self.get_object(request, pk)
        if sub is None:
            messages.error(request, "Subscription not found.")
            return redirect(
                reverse('admin:subscriptions_subscription_changelist')
            )

        if request.method == 'POST':
            try:
                amount_inr = int(request.POST.get('amount_inr') or
                                 sub.monthly_amount_inr or 0)
            except ValueError:
                amount_inr = 0

            method    = (request.POST.get('method') or 'upi')[:20]
            reference = (request.POST.get('reference') or '')[:100]
            notes     = (request.POST.get('notes') or '')[:500]

            # Bump period end by 30 days from today or current end, whichever is later.
            old_end = sub.current_period_end
            new_end = max(old_end, date.today()) + timedelta(days=30)
            sub.current_period_end = new_end
            sub.status = 'active'
            sub.save(update_fields=[
                'current_period_end', 'status', 'updated_at'
            ])

            Payment.objects.create(
                subscription=sub,
                amount_inr=amount_inr,
                method=method,
                reference=reference,
                notes=notes,
                marked_by=request.user,
            )

            messages.success(
                request,
                f"✓ {sub.clinic.name} marked paid · "
                f"₹{amount_inr:,} via {method} · "
                f"valid until {new_end:%d %b %Y}"
            )
            return redirect(
                reverse('admin:subscriptions_subscription_change', args=[pk])
            )

        suggested_new_end = (
            max(sub.current_period_end, date.today()) + timedelta(days=30)
        )
        return render(
            request,
            'admin/subscriptions/subscription/mark_paid_confirm.html',
            {
                'sub': sub,
                'today': date.today(),
                'suggested_new_end': suggested_new_end,
                'opts': self.model._meta,
                'site_header': self.admin_site.site_header,
                'title': f'Mark {sub.clinic.name} as paid',
                'has_permission': True,
                'is_popup': False,
                'site_url': '/',
            },
        )

    # ── List display helpers ─────────────────────────────────
    def clinic_link(self, obj):
        url = reverse('admin:clinic_clinic_change', args=[obj.clinic_id])
        return format_html(
            '<a href="{}">{}</a><br>'
            '<span style="font-family:monospace;font-size:11px;'
            'color:#71717a">{}</span>',
            url, obj.clinic.name, obj.clinic.clinic_code,
        )
    clinic_link.short_description = 'Clinic'
    clinic_link.admin_order_field = 'clinic__name'

    def tier_pill(self, obj):
        colors = {
            'basic':    ('#27272a', '#a1a1aa'),
            'standard': ('#1e1b4b', '#818cf8'),
            'premium':  ('#14532d', '#4ade80'),
        }
        bg, fg = colors.get(obj.tier, ('#27272a', '#a1a1aa'))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:500">{}</span>',
            bg, fg, obj.get_tier_display().split('—')[0].strip(),
        )
    tier_pill.short_description = 'Tier'

    def status_pill(self, obj):
        colors = {
            'pilot':     ('#1e3a5f', '#60a5fa'),
            'active':    ('#14532d', '#4ade80'),
            'past_due':  ('#78350f', '#fbbf24'),
            'suspended': ('#7c2d12', '#fb923c'),
            'cancelled': ('#3f3f46', '#71717a'),
        }
        bg, fg = colors.get(obj.status, ('#3f3f46', '#71717a'))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:500">{}</span>',
            bg, fg, obj.get_status_display().split('—')[0].strip(),
        )
    status_pill.short_description = 'Status'

    def days_display(self, obj):
        d = obj.days_until_expiry
        if d < 0:
            return format_html(
                '<span style="color:#ef4444;font-family:monospace">'
                '{}d overdue</span>', abs(d)
            )
        if d <= 3:
            return format_html(
                '<span style="color:#f59e0b;font-family:monospace">'
                '{}d left</span>', d
            )
        return format_html(
            '<span style="color:#71717a;font-family:monospace">'
            '{}d</span>', d
        )
    days_display.short_description = 'Expiry'

    def amount_display(self, obj):
        if not obj.monthly_amount_inr:
            return format_html('<span style="color:#3f3f46">—</span>')
        return format_html(
            '<span style="font-family:monospace">₹{:,}</span>',
            obj.monthly_amount_inr,
        )
    amount_display.short_description = '₹/mo'

    def payment_count(self, obj):
        n = obj.payments.count()
        if not n:
            return format_html('<span style="color:#3f3f46">0</span>')
        return format_html(
            '<span style="font-family:monospace">{}</span>', n
        )
    payment_count.short_description = 'Payments'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display  = ('subscription', 'amount_inr', 'method',
                     'reference', 'paid_at', 'marked_by')
    list_filter   = ('method', 'paid_at')
    search_fields = ('subscription__clinic__name',
                     'subscription__clinic__clinic_code',
                     'reference')
    readonly_fields = ('paid_at', 'created_at', 'marked_by')
    ordering = ('-paid_at',)
