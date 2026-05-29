from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import Clinic, Doctor, Patient, AvailableSlot, Appointment


# ────────────────────────────────────────────────────────────────────
# Tiny helper — colored pill badge
# ────────────────────────────────────────────────────────────────────
def _pill(text, bg, fg='#fff'):
    return format_html(
        '<span style="background:{};color:{};padding:2px 9px;border-radius:999px;'
        'font-size:11px;font-weight:600;letter-spacing:.02em;'
        'display:inline-block;">{}</span>',
        bg, fg, text,
    )


# ────────────────────────────────────────────────────────────────────
# Clinic — clean sectioned form
# ────────────────────────────────────────────────────────────────────
@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):

    # ─── Custom templates — card grid + hero detail page ───────────
    change_list_template = 'admin/clinic/clinic/change_list.html'
    change_form_template = 'admin/clinic/clinic/change_form.html'

    # ─── List view (fallback table still works for search/sort) ────
    list_display = ('name_with_code', 'wa_pill', 'maps_pill', 'doctors_pill', 'created_at')
    search_fields = ('name', 'clinic_code', 'display_phone_number', 'phone_number_id')
    ordering = ('-created_at',)

    # ─── Inject hero stats into both list + detail context ─────────
    def changelist_view(self, request, extra_context=None):
        from django.db.models import Q
        ctx = extra_context or {}
        ctx['cc_stats'] = {
            'live': Clinic.objects.exclude(
                Q(display_phone_number='') & Q(whatsapp_number='')
            ).count(),
            'doctors': Doctor.objects.filter(is_registered=True).count(),
            'appts': Appointment.objects.count(),
        }
        return super().changelist_view(request, extra_context=ctx)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        from datetime import date, timedelta
        ctx = extra_context or {}
        clinic = self.get_object(request, object_id)
        if clinic:
            today = date.today()
            week_end = today + timedelta(days=7)
            month_ago = today - timedelta(days=30)
            doctors_total = clinic.doctors.count()
            has_wa = bool(clinic.display_phone_number or clinic.whatsapp_number)
            has_map = bool(clinic.location_map_url)
            has_doctors = doctors_total > 0
            has_hours = bool(clinic.operating_hours) or bool(clinic.working_hours)
            has_address = bool(clinic.address)
            has_token_or_default = True  # uses platform fallback if blank — always "ok"
            setup_total = 6
            setup_done = sum([
                has_wa, has_map, has_doctors,
                has_hours, has_address, has_token_or_default,
            ])
            ctx['cc'] = {
                'doctors_total': doctors_total,
                'doctors_registered': clinic.doctors.filter(is_registered=True).count(),
                'appts_total': clinic.appointments.count(),
                'appts_today': clinic.appointments.filter(slot__date=today).count(),
                'slots_booked_7d': AvailableSlot.objects.filter(
                    doctor__clinic=clinic, date__gte=today, date__lt=week_end, is_booked=True
                ).count(),
                'slots_unbooked_7d': AvailableSlot.objects.filter(
                    doctor__clinic=clinic, date__gte=today, date__lt=week_end, is_booked=False
                ).count(),
                'patients_total': Patient.objects.filter(
                    appointments__clinic=clinic
                ).distinct().count(),
                'no_shows_30d': clinic.appointments.filter(
                    status='no_show', slot__date__gte=month_ago
                ).count(),
                'setup_total': setup_total,
                'setup_done': setup_done,
            }
        return super().change_view(request, object_id, form_url, extra_context=ctx)

    # ─── Form layout ───────────────────────────────────────────────
    fieldsets = (
        ('General', {
            'fields': ('name', 'clinic_code', 'address'),
            'description': "Basic information shown across the dashboard and patient messages.",
        }),
        ('Location', {
            'fields': ('location_map_url',),
            'description': "Google Maps link used in patient reminders so they can tap to navigate.",
        }),
        ('Operating hours', {
            'fields': ('working_days', 'working_hours', 'operating_hours', 'slot_minutes'),
            'description': mark_safe(
                "<b>Display text</b> is shown to patients. <b>Operating hours</b> is the JSON the "
                "booking flow actually uses — example "
                "<code>{\"mon\":[[\"09:00\",\"13:00\"],[\"16:00\",\"21:00\"]], \"sun\":[]}</code>. "
                "Leave blank for default (Mon-Sat 9-1 &amp; 4-9)."
            ),
        }),
        ('WhatsApp', {
            'fields': ('display_phone_number', 'whatsapp_number', 'phone_number_id', 'owner_number'),
            'description': "The Meta-registered WhatsApp number. Use digits with country code, no plus sign.",
        }),
        ('Advanced', {
            'fields': ('access_token',),
            'description': "Leave blank to use the platform-wide System User token. "
                           "Override only if this clinic uses its own dedicated token.",
            'classes': ('collapse',),
        }),
    )

    # ─── List-display formatters ───────────────────────────────────
    def name_with_code(self, obj):
        return format_html(
            '<b>{}</b><br><span style="color:#94a3b8;font-family:monospace;font-size:11px;">{}</span>',
            obj.name, obj.clinic_code,
        )
    name_with_code.short_description = 'Clinic'
    name_with_code.admin_order_field = 'name'

    def wa_pill(self, obj):
        number = (obj.display_phone_number or obj.whatsapp_number or '').lstrip('+')
        if not number:
            return _pill('not set', '#94a3b8')
        link = f"https://wa.me/{number}"
        return format_html(
            '<a href="{}" target="_blank" style="text-decoration:none;">'
            '<span style="background:#10b981;color:#fff;padding:2px 9px;border-radius:999px;'
            'font-size:11px;font-weight:600;">📱 +{}</span></a>',
            link, number,
        )
    wa_pill.short_description = 'WhatsApp'

    def maps_pill(self, obj):
        if not obj.location_map_url:
            return _pill('not set', '#94a3b8')
        return format_html(
            '<a href="{}" target="_blank" style="text-decoration:none;">'
            '<span style="background:#3b82f6;color:#fff;padding:2px 9px;border-radius:999px;'
            'font-size:11px;font-weight:600;">📍 Open</span></a>',
            obj.location_map_url,
        )
    maps_pill.short_description = 'Maps'

    def doctors_pill(self, obj):
        n = obj.doctors.filter(is_registered=True).count()
        color = '#10b981' if n else '#f59e0b'
        return _pill(f'{n} registered', color)
    doctors_pill.short_description = 'Doctors'


# ────────────────────────────────────────────────────────────────────
# Doctor / Patient / Slot / Appointment — unchanged
# ────────────────────────────────────────────────────────────────────
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


# ════════════════════════════════════════════════════════════
# MessageTemplate — clean admin with colored status badges
# ════════════════════════════════════════════════════════════
from .models import MessageTemplate


# Zinc-on-surface neutrals + semantic-only colors. Status uses the success/warning/danger
# tokens; everything else gets a quiet surface-3 chip — same approach as the clinic detail page.
_STATUS_COLORS = {
    'draft':     ('#1f1f23', '#a1a1aa'),  # surface-3 / text-2
    'pending':   ('rgba(251,191,36,.14)',  '#fbbf24'),  # warning
    'approved':  ('rgba(52,211,153,.14)',  '#34d399'),  # success
    'rejected':  ('rgba(248,113,113,.14)', '#f87171'),  # danger
    'paused':    ('rgba(129,140,248,.14)', '#a5b4fc'),  # accent-soft
    'disabled':  ('#1f1f23', '#71717a'),  # surface-3 / text-3
}
_CATEGORY_COLORS = {
    'UTILITY':        ('#1f1f23', '#a1a1aa'),
    'MARKETING':      ('rgba(129,140,248,.14)', '#a5b4fc'),  # indigo
    'AUTHENTICATION': ('#1f1f23', '#a1a1aa'),
}


def _pill2(text, bg, fg):
    """Recolored pill — two-tone (bg, fg), restrained zinc/indigo look."""
    return format_html(
        '<span style="background:{};color:{};padding:2px 9px;border-radius:999px;'
        'font-size:11px;font-weight:500;letter-spacing:.01em;'
        'display:inline-block;font-feature-settings:\'tnum\';">{}</span>',
        bg, fg, text,
    )


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):

    # ─── Custom list (Phase 1) + dual-mode change_form (Phase 2) ───
    # change_form.html detects `add` mode: renders the 5-step wizard;
    # on edit it falls through to Django's stock form via {{ block.super }}.
    change_list_template = 'admin/clinic/messagetemplate/change_list.html'
    change_form_template = 'admin/clinic/messagetemplate/change_form.html'

    list_display = ('name', 'lang_pill', 'category_pill', 'status_pill',
                    'scope_pill', 'updated_at')
    list_filter = ('status', 'category', 'language', 'is_generic')
    search_fields = ('name', 'body', 'meta_template_id')
    filter_horizontal = ('clinics',)
    readonly_fields = ('created_at', 'updated_at', 'preview')

    # ─── Inject per-tab counts + status counts into list context ───
    def changelist_view(self, request, extra_context=None):
        ctx = extra_context or {}
        from django.db.models import Count, Q
        qs = MessageTemplate.objects.all()
        # Status counts for header summary + chip count badges.
        by_status = {row['status']: row['n'] for row in
                     qs.values('status').annotate(n=Count('id'))}
        by_category = {row['category']: row['n'] for row in
                       qs.values('category').annotate(n=Count('id'))}
        # "Needs attention" = rejected OR (not generic AND no clinics linked).
        needs_attention = qs.filter(
            Q(status='rejected') |
            Q(is_generic=False, clinics__isnull=True)
        ).distinct().count()
        ctx['mt_counts'] = {
            'total':     qs.count(),
            'approved':  by_status.get('approved', 0),
            'pending':   by_status.get('pending', 0),
            'rejected':  by_status.get('rejected', 0),
            'draft':     by_status.get('draft', 0),
            'paused':    by_status.get('paused', 0),
            'disabled':  by_status.get('disabled', 0),
            'utility':   by_category.get('UTILITY', 0),
            'marketing': by_category.get('MARKETING', 0),
            'auth':      by_category.get('AUTHENTICATION', 0),
            'needs_attention': needs_attention,
        }
        return super().changelist_view(request, extra_context=ctx)

    # ─── Inject wizard context on /add/ (clinic picker, model choices) ─
    def add_view(self, request, form_url='', extra_context=None):
        ctx = extra_context or {}
        ctx['mt_wizard'] = {
            'clinics': [
                {'id': c.pk, 'name': c.name, 'code': c.clinic_code}
                for c in Clinic.objects.order_by('name')
            ],
            'categories': MessageTemplate.CATEGORY_CHOICES,
            'languages':  MessageTemplate.LANGUAGE_CHOICES,
        }
        return super().add_view(request, form_url, extra_context=ctx)

    fieldsets = (
        ('Template', {
            'fields': ('name', 'language', 'category', 'status'),
        }),
        ('Content', {
            'fields': ('body', 'variables', 'preview'),
            'description': mark_safe(
                "Use <code>{{1}}</code>, <code>{{2}}</code>, etc. for variables. "
                "<code>*text*</code> renders as bold in WhatsApp."
            ),
        }),
        ('Scope — who can use this template', {
            'fields': ('is_generic', 'clinics'),
            'description': "Tick the box to allow all clinics. Otherwise pick specific clinics below.",
        }),
        ('Meta details', {
            'fields': ('meta_template_id', 'notes'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ─── List badges (zinc/indigo, semantic-only) ──────────────────
    def lang_pill(self, obj):
        return _pill2(obj.language.upper(), '#1f1f23', '#a1a1aa')
    lang_pill.short_description = 'Lang'

    def category_pill(self, obj):
        bg, fg = _CATEGORY_COLORS.get(obj.category, ('#1f1f23', '#a1a1aa'))
        return _pill2(obj.get_category_display(), bg, fg)
    category_pill.short_description = 'Category'

    def status_pill(self, obj):
        bg, fg = _STATUS_COLORS.get(obj.status, ('#1f1f23', '#a1a1aa'))
        return _pill2(obj.get_status_display().split(' — ')[0], bg, fg)
    status_pill.short_description = 'Status'

    def scope_pill(self, obj):
        if obj.is_generic:
            return _pill2('All clinics', 'rgba(52,211,153,.14)', '#34d399')
        n = obj.clinics.count()
        if n == 0:
            return _pill2('No clinics linked', 'rgba(248,113,113,.14)', '#f87171')
        return _pill2(f'{n} clinic{"" if n == 1 else "s"}', '#1f1f23', '#a1a1aa')
    scope_pill.short_description = 'Available to'

    # ─── WhatsApp-style preview on detail page ─────────────────────
    def preview(self, obj):
        if not obj or not obj.body:
            return mark_safe('<em style="color:#94a3b8;">Save once to see a preview.</em>')
        import re
        body = (obj.body or '')
        # escape HTML, then render bold and variable highlights
        body = (body.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        body = re.sub(r'\*([^*\n]+)\*', r'<b>\1</b>', body)
        body = re.sub(r'\{\{(\d+)\}\}',
                      r'<span style="color:#0369a1;font-weight:700;">{{\1}}</span>',
                      body).replace('\n', '<br>')
        return mark_safe(
            '<div style="max-width:340px;background:#dcf8c6;padding:10px 14px;'
            'border-radius:10px;font-size:13px;line-height:1.55;color:#0f172a;'
            'font-family:-apple-system,BlinkMacSystemFont,sans-serif;">' + body + '</div>'
        )
    preview.short_description = 'WhatsApp preview'
