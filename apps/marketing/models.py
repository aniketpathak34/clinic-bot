from django.db import models


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
            "Any of these works:<br>"
            " • https://youtu.be/XXXXX<br>"
            " • https://www.youtube.com/watch?v=XXXXX<br>"
            " • https://www.youtube.com/shorts/XXXXX (portrait autoplayer)"
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
        """Extract the YouTube video ID so we can build a clean embed URL.

        Handles watch URLs, youtu.be short links, /embed/ and /shorts/ formats.
        """
        if not self.embed_url:
            return ''
        url = self.embed_url.strip()
        for marker in ('v=', 'youtu.be/', 'embed/', 'shorts/'):
            if marker in url:
                rest = url.split(marker, 1)[1]
                return rest.split('&')[0].split('?')[0].split('/')[0]
        return ''

    @property
    def is_youtube(self) -> bool:
        return 'youtube.com' in (self.embed_url or '') or 'youtu.be' in (self.embed_url or '')

    @property
    def is_youtube_short(self) -> bool:
        """True if the URL is a YouTube Short (portrait). Used for aspect ratio."""
        return '/shorts/' in (self.embed_url or '')

    @property
    def embed_iframe_src(self) -> str:
        """YouTube iframe-safe URL. Uses youtube-nocookie.com which is:
         - Allowed by most ad-blockers / privacy extensions
         - GDPR-friendly (no tracking cookies until playback)
         - Drop-in compatible with regular /embed/ URLs
        """
        vid = self.youtube_id
        return f"https://www.youtube-nocookie.com/embed/{vid}?rel=0" if vid else ''

    @property
    def watch_url(self) -> str:
        """Plain YouTube watch URL — useful as a fallback link."""
        vid = self.youtube_id
        return f"https://www.youtube.com/watch?v={vid}" if vid else ''

    @property
    def file_url(self) -> str:
        return self.video_file.url if self.video_file else ''
