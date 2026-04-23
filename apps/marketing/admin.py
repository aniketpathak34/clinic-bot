from django.contrib import admin
from django.utils.html import format_html

from .models import DemoVideo


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
