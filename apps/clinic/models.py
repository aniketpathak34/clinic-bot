from django.db import models


class Clinic(models.Model):
    name = models.CharField(max_length=200)
    clinic_code = models.CharField(max_length=20, unique=True)
    whatsapp_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.clinic_code})"


class Doctor(models.Model):
    SPECIALTY_CHOICES = [
        ('general', 'General Physician'),
        ('dentist', 'Dentist'),
        ('gynecologist', 'Gynecologist'),
        ('pediatrician', 'Pediatrician'),
        ('dermatologist', 'Dermatologist'),
        ('ent', 'ENT Specialist'),
        ('orthopedic', 'Orthopedic'),
        ('other', 'Other'),
    ]

    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='doctors')
    name = models.CharField(max_length=200)
    whatsapp_number = models.CharField(max_length=15, unique=True)
    specialty = models.CharField(max_length=50, choices=SPECIALTY_CHOICES, default='general')
    is_registered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Dr. {self.name} ({self.get_specialty_display()})"


class Patient(models.Model):
    LANGUAGE_CHOICES = [
        ('en', 'English'),
        ('hi', 'Hindi'),
        ('mr', 'Marathi'),
    ]

    whatsapp_number = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=200, blank=True)
    age = models.PositiveIntegerField(null=True, blank=True)
    language_preference = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='en')
    is_registered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name or 'Unknown'} ({self.whatsapp_number})"


class AvailableSlot(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='slots')
    date = models.DateField()
    time = models.TimeField()
    is_booked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('doctor', 'date', 'time')
        ordering = ['date', 'time']

    def __str__(self):
        status = "Booked" if self.is_booked else "Available"
        return f"Dr. {self.doctor.name} - {self.date} {self.time} ({status})"


class Appointment(models.Model):
    STATUS_CHOICES = [
        ('booked', 'Booked'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('no_show', 'No Show'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='appointments')
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name='appointments')
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='appointments')
    slot = models.ForeignKey(AvailableSlot, on_delete=models.CASCADE, related_name='appointments')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='booked')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient.name} → Dr. {self.doctor.name} on {self.slot.date} at {self.slot.time} [{self.status}]"

    def save(self, *args, **kwargs):
        """Auto-free slot when appointment is cancelled/completed/no_show."""
        super().save(*args, **kwargs)
        if self.status in ('cancelled', 'no_show') and self.slot.is_booked:
            self.slot.is_booked = False
            self.slot.save()

    def delete(self, *args, **kwargs):
        """Free slot when appointment is deleted (e.g., from admin)."""
        slot = self.slot
        super().delete(*args, **kwargs)
        if slot.is_booked:
            # Only free if no other booked appointment uses this slot
            if not Appointment.objects.filter(slot=slot, status='booked').exists():
                slot.is_booked = False
                slot.save()
