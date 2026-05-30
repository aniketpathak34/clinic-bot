from datetime import date

from django.conf import settings
from django.db import models


TIER_CHOICES = [
    ('basic',    'Basic — ₹999/mo'),
    ('standard', 'Standard — ₹1,999/mo'),
    ('premium',  'Premium — ₹2,999/mo'),
]

STATUS_CHOICES = [
    ('pilot',     'Free pilot'),
    ('active',    'Active'),
    ('past_due',  'Past due — grace period (7 days)'),
    ('suspended', 'Suspended — soft block'),
    ('cancelled', 'Cancelled — full stop'),
]

TIER_FEATURES = {
    'basic': {
        'day_before_reminders':  True,
        'hour_before_reminders': False,
        'daily_owner_summary':   False,
        'ai_enquiry':            False,
        'multilingual':          False,
    },
    'standard': {
        'day_before_reminders':  True,
        'hour_before_reminders': True,
        'daily_owner_summary':   True,
        'ai_enquiry':            False,
        'multilingual':          False,
    },
    'premium': {
        'day_before_reminders':  True,
        'hour_before_reminders': True,
        'daily_owner_summary':   True,
        'ai_enquiry':            True,
        'multilingual':          True,
    },
}


class Subscription(models.Model):
    clinic = models.OneToOneField(
        'clinic.Clinic',
        on_delete=models.CASCADE,
        related_name='subscription',
    )
    tier   = models.CharField(max_length=20, choices=TIER_CHOICES, default='basic')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pilot')

    started_at          = models.DateField()
    current_period_end  = models.DateField()
    pilot_ends_at       = models.DateField(null=True, blank=True)

    monthly_amount_inr  = models.PositiveIntegerField(
        default=0,
        help_text="Agreed monthly amount in INR. 0 = pilot/free.")
    notes = models.TextField(
        blank=True,
        help_text="Internal billing notes — UPI ref, special terms, etc.")

    # Future enforcement columns — null = unlimited for now.
    doctors_limit              = models.PositiveIntegerField(null=True, blank=True)
    monthly_conversation_limit = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'
        ordering = ['-created_at']

    def __str__(self):
        return (f"{self.clinic.clinic_code} — "
                f"{self.get_tier_display()} — {self.get_status_display()}")

    def allows(self, feature: str) -> bool:
        """True iff tier includes `feature` AND status is active-enough.

        Active states for feature access: pilot, active, past_due.
        Suspended and cancelled get nothing.
        """
        if self.status in ('suspended', 'cancelled'):
            return False
        return TIER_FEATURES.get(self.tier, {}).get(feature, False)

    def is_active_for_patients(self) -> bool:
        """pilot / active / past_due → bot works. suspended / cancelled → soft block."""
        return self.status in ('pilot', 'active', 'past_due')

    @property
    def days_until_expiry(self) -> int:
        """Days until current_period_end. Negative = already expired."""
        return (self.current_period_end - date.today()).days


class Payment(models.Model):
    """Audit trail for every offline payment marked by an admin operator."""

    METHOD_CHOICES = [
        ('upi',           'UPI'),
        ('bank_transfer', 'Bank transfer'),
        ('cash',          'Cash'),
        ('other',         'Other'),
    ]

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='payments')
    amount_inr = models.PositiveIntegerField()
    method     = models.CharField(max_length=20, choices=METHOD_CHOICES, default='upi')
    reference  = models.CharField(
        max_length=100, blank=True,
        help_text="UPI transaction ID, bank ref, etc.")
    notes      = models.TextField(blank=True)
    marked_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    paid_at    = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        ordering = ['-paid_at']

    def __str__(self):
        return (f"₹{self.amount_inr:,} via {self.method} "
                f"on {self.paid_at} — {self.subscription.clinic.clinic_code}")
