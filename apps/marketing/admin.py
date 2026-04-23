from django.contrib import admin
from django.utils.html import format_html

from .models import DemoVideo, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'bot_number', 'contact_number', 'contact_name', 'updated_at')
    fieldsets = (
        ('Landing page CTAs', {
            'fields': ('bot_number', 'contact_number', 'contact_name'),
            'description': (
                "<b>bot_number</b> — the WhatsApp number patients message to try the bot. "
                "This is your Meta WhatsApp number (e.g. <code>15551773718</code>).<br>"
                "<b>contact_number</b> — your personal WhatsApp. Shown in the "
                "\"About / Contact\" block so visitors can reach you directly.<br>"
                "Enter digits only, with country code. No + or spaces."
            ),
        }),
    )

    # Enforce singleton — no add, no delete, only edit the single row.
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Redirect the list page straight to the edit form — less clicks.
        from django.shortcuts import redirect
        obj = SiteSettings.get()
        return redirect(f'../sitesettings/{obj.pk}/change/')


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
