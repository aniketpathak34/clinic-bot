from django.db import models
from apps.clinic.models import Appointment


class CallLog(models.Model):
    """Tracks automated confirmation calls made to patients."""
    STATUS_CHOICES = [
        ('initiated', 'Initiated'),
        ('confirmed', 'Patient Confirmed'),
        ('cancelled', 'Patient Cancelled via Call'),
        ('no_answer', 'No Answer'),
        ('failed', 'Call Failed'),
    ]

    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name='call_logs')
    phone_number = models.CharField(max_length=15)
    call_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
    attempt_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Call to {self.phone_number} for Appt#{self.appointment.id} - {self.status}"
