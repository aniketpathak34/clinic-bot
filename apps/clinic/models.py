from datetime import datetime, time, timedelta

from django.db import models


# Sensible default if a clinic hasn't set its own hours yet:
# Mon-Sat with split shifts 9am-1pm and 4pm-9pm; closed Sunday.
DEFAULT_OPERATING_HOURS = {
    "mon": [["09:00", "13:00"], ["16:00", "21:00"]],
    "tue": [["09:00", "13:00"], ["16:00", "21:00"]],
    "wed": [["09:00", "13:00"], ["16:00", "21:00"]],
    "thu": [["09:00", "13:00"], ["16:00", "21:00"]],
    "fri": [["09:00", "13:00"], ["16:00", "21:00"]],
    "sat": [["09:00", "13:00"]],
    "sun": [],
}

_WEEKDAY_KEY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Clinic(models.Model):
    name = models.CharField(max_length=200)
    clinic_code = models.CharField(max_length=20, unique=True)
    whatsapp_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)

    # Meta WhatsApp Cloud API (per-clinic)
    phone_number_id = models.CharField(max_length=50, blank=True, db_index=True)
    display_phone_number = models.CharField(max_length=20, blank=True, db_index=True)
    access_token = models.TextField(blank=True)
    owner_number = models.CharField(max_length=15, blank=True)
    working_hours = models.CharField(max_length=100, blank=True,
                                     help_text="Display-only text like 'Mon-Sat 9am-1pm, 4pm-9pm'")
    working_days = models.CharField(max_length=50, blank=True,
                                    help_text="Display-only text like 'Mon-Sat'")

    # Structured operating hours. Format:
    # {"mon": [["09:00","13:00"], ["16:00","21:00"]], ..., "sun": []}
    # Empty list = closed that day. Multiple pairs = split shifts.
    operating_hours = models.JSONField(
        default=dict, blank=True,
        help_text=(
            "Per-weekday shifts. Example: "
            '{"mon":[["09:00","13:00"],["16:00","21:00"]], "sun":[]}. '
            "Leave blank to use defaults (Mon-Sat 9-1 & 4-9)."
        ),
    )
    slot_minutes = models.PositiveIntegerField(
        default=30,
        help_text="Slot granularity in minutes (usually 15 or 30)",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.clinic_code})"

    @classmethod
    def find_by_display_number(cls, display_number: str):
        if not display_number:
            return None
        normalized = display_number.lstrip('+')
        return cls.objects.filter(display_phone_number=normalized).first() \
            or cls.objects.filter(whatsapp_number=normalized).first()

    # ─── Operating-hours helpers ─────────────────────────────────

    def _hours_map(self) -> dict:
        """Return the per-weekday shift map, falling back to sane defaults."""
        return self.operating_hours if self.operating_hours else DEFAULT_OPERATING_HOURS

    def get_shifts(self, day) -> list:
        """List of (open_time, close_time) tuples for the given date's weekday.
        Empty list = clinic is closed that day.
        """
        key = _WEEKDAY_KEY[day.weekday()]
        raw_shifts = self._hours_map().get(key, [])
        out = []
        for start_str, end_str in raw_shifts:
            try:
                out.append((
                    datetime.strptime(start_str, "%H:%M").time(),
                    datetime.strptime(end_str, "%H:%M").time(),
                ))
            except (ValueError, TypeError):
                continue
        return out

    def is_open(self, day) -> bool:
        return bool(self.get_shifts(day))

    def get_slot_times(self, day) -> list:
        """Every valid slot-start time for this date, at slot_minutes granularity.
        Last slot start = close_time - slot_minutes so the slot fits before close.
        """
        step = max(5, int(self.slot_minutes or 30))
        slots = []
        today = day
        for open_t, close_t in self.get_shifts(day):
            cursor = datetime.combine(today, open_t)
            close_dt = datetime.combine(today, close_t)
            while cursor + timedelta(minutes=step) <= close_dt:
                slots.append(cursor.time())
                cursor += timedelta(minutes=step)
        return slots

    def get_morning_slots(self, day) -> list:
        """Slots that start before 13:00 (noon session)."""
        return [t for t in self.get_slot_times(day) if t.hour < 13]

    def get_afternoon_slots(self, day) -> list:
        """Slots that start at or after 13:00 (evening session)."""
        return [t for t in self.get_slot_times(day) if t.hour >= 13]


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
    welcomed_at = models.DateTimeField(null=True, blank=True,
                                       help_text="Set once the welcome WhatsApp is sent")
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
    hour_before_reminded_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Set when the 1-hour-before WhatsApp reminder was sent"
    )
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
