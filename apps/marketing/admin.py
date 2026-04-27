from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import DemoVideo, Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('score', 'name', 'phone_link', 'rating_display', 'reviews',
                    'status', 'whatsapp_button', 'created_at')
    list_display_links = ('name',)
    list_filter = ('status', 'rating')
    list_editable = ('status',)
    search_fields = ('name', 'phone', 'address')
    readonly_fields = ('place_id', 'last_seen_at', 'created_at')
    ordering = ('-score', '-created_at')
    actions = ['mark_as_sent', 'mark_as_replied', 'mark_as_not_interested']
    change_list_template = 'admin/marketing/lead/change_list.html'

    # ─── Custom admin URL: "Run lead-gen now" ─────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'run-leadgen-now/',
                self.admin_site.admin_view(self.run_leadgen_view),
                name='marketing_lead_run_leadgen',
            ),
        ]
        return custom + urls

    def run_leadgen_view(self, request):
        """Synchronous trigger — runs Google Places scraper inline.
        No Celery worker needed; takes ~5-10 seconds."""
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        try:
            call_command('seed_leads', stdout=out, stderr=out)
            self.message_user(
                request,
                f"✓ Lead-gen complete. {out.getvalue().splitlines()[-1] if out.getvalue() else ''}",
                level=messages.SUCCESS,
            )
        except Exception as e:
            self.message_user(request, f"❌ Lead-gen failed: {e}", level=messages.ERROR)
        return HttpResponseRedirect(reverse('admin:marketing_lead_changelist'))

    fieldsets = (
        (None, {
            'fields': ('name', 'phone', 'rating', 'reviews', 'address',
                       'google_maps_url', 'types'),
        }),
        ('Pipeline', {
            'fields': ('score', 'status', 'notes', 'contacted_at'),
        }),
        ('Source', {
            'classes': ('collapse',),
            'fields': ('place_id', 'last_seen_at', 'created_at'),
        }),
    )

    def phone_link(self, obj):
        return format_html('<a href="tel:+{0}">+{0}</a>', obj.phone)
    phone_link.short_description = 'Phone'

    def rating_display(self, obj):
        if obj.rating is None:
            return '—'
        return f"★ {obj.rating}"
    rating_display.short_description = 'Rating'

    def whatsapp_button(self, obj):
        if obj.status in ('pilot', 'not_interested', 'invalid'):
            return '—'
        return format_html(
            '<a href="{}" target="_blank" '
            'style="background:#25D366;color:white;padding:4px 10px;'
            'border-radius:4px;text-decoration:none;font-weight:600;">💬 Send</a>',
            obj.whatsapp_link,
        )
    whatsapp_button.short_description = 'Outreach'

    def mark_as_sent(self, request, queryset):
        updated = queryset.update(status='sent', contacted_at=timezone.now())
        self.message_user(request, f"{updated} lead(s) marked as Sent.")
    mark_as_sent.short_description = "Mark selected as Sent"

    def mark_as_replied(self, request, queryset):
        updated = queryset.update(status='replied')
        self.message_user(request, f"{updated} lead(s) marked as Replied.")
    mark_as_replied.short_description = "Mark selected as Replied"

    def mark_as_not_interested(self, request, queryset):
        updated = queryset.update(status='not_interested')
        self.message_user(request, f"{updated} lead(s) marked as Not interested.")
    mark_as_not_interested.short_description = "Mark selected as Not interested"


@admin.register(DemoVideo)
class DemoVideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'role', 'order', 'is_active', 'preview', 'uploaded_at')
    list_editable = ('order', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = ('title', 'description')
    fieldsets = (
        (None, {
            'fields': ('title', 'role', 'description'),
        }),
        ('Video source', {
            'fields': ('embed_url', 'video_file', 'poster'),
            'description': (
                "Pick <b>one</b> of the two. YouTube/Vimeo URL is strongly "
                "preferred on Render free tier — uploaded files are wiped on every deploy."
            ),
        }),
        ('Display', {
            'fields': ('order', 'is_active'),
        }),
    )

    def preview(self, obj):
        if obj.is_youtube and obj.youtube_id:
            return format_html(
                '<a href="https://youtu.be/{}" target="_blank">▶ YouTube</a>', obj.youtube_id
            )
        if obj.video_file:
            return format_html('<a href="{}" target="_blank">▶ File</a>', obj.video_file.url)
        return '—'
    preview.short_description = 'Preview'
