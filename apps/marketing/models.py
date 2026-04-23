from django.db import models


class SiteSettings(models.Model):
    """Single-row config edited from Django admin.

    Holds the two WhatsApp numbers shown on the landing page:
    * bot_number     — what patients message to try the live demo
    * contact_number — your personal WhatsApp, shown in the "About / Contact" block
    """
    bot_number = models.CharField(
        max_length=20, blank=True,
        help_text="Digits only, with country code. E.g. 15551773718 (Meta test bot).",
    )
    contact_number = models.CharField(
        max_length=20, blank=True,
        help_text="Digits only, with country code. Your personal WhatsApp for enquiries.",
    )
    contact_name = models.CharField(
        max_length=80, default='Aniket',
        help_text="Name shown in CTA text (e.g. \"Chat with {name}\").",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self):
        return "Landing page settings"

    def save(self, *args, **kwargs):
        # Singleton — force the primary key to 1 so admin users can't create duplicates.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # No-op — prevent accidental deletion from admin.
        pass

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # Helpers — strip "+" and spaces so templates always get a clean digits-only form.
    @property
    def clean_bot_number(self) -> str:
        return (self.bot_number or '').lstrip('+').replace(' ', '')

    @property
    def clean_contact_number(self) -> str:
        return (self.contact_number or '').lstrip('+').replace(' ', '')


class DemoVideo(models.Model):
    ROLE_CHOICES = [
        ('patient', 'Patient flow'),
        ('provider', 'Provider / Doctor flow'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    description = models.TextField(
        blank=True,
        help_text="Short caption shown under the video on the landing page.",
    )

    # Pick one — embed URL is preferred on Render free tier (ephemeral FS).
    embed_url = models.URLField(
        blank=True,
        help_text=(
            "YouTube / Vimeo link. Works on Render free tier (recommended). "
            "Paste the full URL like https://youtu.be/xxxxx or "
            "https://www.youtube.com/watch?v=xxxxx"
        ),
    )
    video_file = models.FileField(
        upload_to='demo_videos/', blank=True, null=True,
        help_text=(
            "Optional direct upload. ⚠️ On Render free tier, uploaded files "
            "are lost on every redeploy — prefer a YouTube URL above for production."
        ),
    )

    poster = models.ImageField(
        upload_to='demo_posters/', blank=True, null=True,
        help_text="Optional thumbnail shown before the viewer presses play.",
    )

    order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers show first within the same role.",
    )
    is_active = models.BooleanField(default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['role', 'order', '-uploaded_at']

    def __str__(self):
        return f"[{self.get_role_display()}] {self.title}"

    # ─── Helpers used by the landing template ─────────────────────

    @property
    def youtube_id(self) -> str:
        """Extract the YouTube video ID so we can build a clean embed URL."""
        if not self.embed_url:
            return ''
        url = self.embed_url.strip()
        for marker in ('v=', 'youtu.be/', 'embed/'):
            if marker in url:
                rest = url.split(marker, 1)[1]
                return rest.split('&')[0].split('?')[0].split('/')[0]
        return ''

    @property
    def is_youtube(self) -> bool:
        return 'youtube.com' in (self.embed_url or '') or 'youtu.be' in (self.embed_url or '')

    @property
    def embed_iframe_src(self) -> str:
        """YouTube iframe-safe URL. Empty string if not a YouTube link."""
        vid = self.youtube_id
        return f"https://www.youtube.com/embed/{vid}?rel=0" if vid else ''

    @property
    def file_url(self) -> str:
        return self.video_file.url if self.video_file else ''
