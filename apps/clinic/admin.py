from django.contrib import admin
from django.utils.html import format_html
from .models import Clinic, Doctor, Patient, AvailableSlot, Appointment


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ('name', 'clinic_code', 'display_phone_number', 'phone_number_id',
                    'whatsapp_link', 'doctor_count', 'created_at')
    search_fields = ('name', 'clinic_code', 'display_phone_number', 'phone_number_id')
    fieldsets = (
        (None, {
            'fields': ('name', 'clinic_code', 'address', 'working_hours', 'working_days'),
        }),
        ('WhatsApp (Meta Cloud API)', {
            'fields': ('display_phone_number', 'whatsapp_number', 'phone_number_id',
                       'access_token', 'owner_number'),
            'description': (
                "display_phone_number = the clinic's WhatsApp number (without +). "
                "phone_number_id = Meta's internal ID for the number. "
                "access_token = leave blank to use the shared System User token."
            ),
        }),
    )

    def whatsapp_link(self, obj):
        number = (obj.display_phone_number or obj.whatsapp_number or '').lstrip('+')
        if not number:
            return '—'
        link = f"https://wa.me/{number}"
        return format_html('<a href="{}" target="_blank">📱 {}</a>', link, link)
    whatsapp_link.short_description = 'Clinic WhatsApp Link'

    def doctor_count(self, obj):
        return obj.doctors.filter(is_registered=True).count()
    doctor_count.short_description = 'Doctors'


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ('name', 'clinic', 'specialty', 'whatsapp_number', 'is_registered')
    list_filter = ('specialty', 'is_registered', 'clinic')
    search_fields = ('name', 'whatsapp_number')
    list_editable = ('is_registered',)


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('name', 'whatsapp_number', 'age', 'language_preference', 'is_registered')
    list_filter = ('language_preference', 'is_registered')
    search_fields = ('name', 'whatsapp_number')


@admin.register(AvailableSlot)
class AvailableSlotAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'date', 'time', 'is_booked')
    list_filter = ('is_booked', 'date', 'doctor')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'doctor', 'clinic', 'slot', 'status', 'created_at')
    list_filter = ('status', 'clinic', 'doctor')
    search_fields = ('patient__name', 'doctor__name')
