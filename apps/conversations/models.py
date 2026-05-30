from django.db import models


class ConversationState(models.Model):
    USER_TYPE_CHOICES = [
        ('doctor', 'Doctor'),
        ('patient', 'Patient'),
        ('unknown', 'Unknown'),
    ]

    # NOT globally unique anymore — same number can have a separate state row
    # per clinic. Uniqueness is enforced by the composite UniqueConstraint in
    # Meta.constraints below (added in migration 0003).
    whatsapp_number = models.CharField(max_length=15, db_index=True)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='unknown')
    clinic = models.ForeignKey(
        'clinic.Clinic', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='conversations'
    )
    current_flow = models.CharField(max_length=50, blank=True, default='')
    step = models.CharField(max_length=50, blank=True, default='')
    context = models.JSONField(default=dict, blank=True)
    language = models.CharField(max_length=5, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['whatsapp_number', 'clinic'],
                name='uniq_convstate_phone_clinic',
            ),
        ]

    def __str__(self):
        clinic_name = self.clinic.name if self.clinic else 'No clinic'
        return f"{self.whatsapp_number} [{self.user_type}] @ {clinic_name} - {self.current_flow}/{self.step}"

    def reset(self):
        self.current_flow = ''
        self.step = ''
        self.context = {}
        self.clinic = None
        self.save()

    def save(self, *args, **kwargs):
        from apps.utils.phone import normalize_phone
        if self.whatsapp_number:
            self.whatsapp_number = normalize_phone(self.whatsapp_number)
        super().save(*args, **kwargs)
