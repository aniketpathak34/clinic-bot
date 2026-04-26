from urllib.parse import quote

from django.db import models


class Lead(models.Model):
    """Outbound prospect — a clinic discovered via Google Places API.

    The lead-gen task scores each candidate on conversion likelihood and
    keeps the top N as Lead rows the operator works manually.
    """
    STATUS_CHOICES = [
        ('new', 'New — not contacted'),
        ('sent', 'Sent — awaiting reply'),
        ('replied', 'Replied — engaging'),
        ('demo_booked', 'Demo booked'),
        ('pilot', 'Pilot signed 🎉'),
        ('not_interested', 'Not interested'),
        ('invalid', 'Invalid / wrong number'),
    ]

    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, db_index=True, unique=True,
                             help_text="Digits only with country code, e.g. 919876543210")
    address = models.CharField(max_length=300, blank=True)
    rating = models.FloatField(null=True, blank=True)
    reviews = models.PositiveIntegerField(default=0)
    types = models.CharField(max_length=200, blank=True,
                             help_text="Comma-separated Google Place types")
    google_maps_url = models.URLField(blank=True)
    place_id = models.CharField(max_length=100, blank=True, db_index=True,
                                help_text="Google's stable Place ID")

    # Our own attribution / pipeline
    score = models.IntegerField(default=0, db_index=True,
                                help_text="Higher = better fit for our pilot")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    notes = models.TextField(blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True,
                                        help_text="Last time the scraper saw this place")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-score', '-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.name} ({self.phone})"

    @property
    def whatsapp_link(self) -> str:
        """Pre-filled wa.me link with the standard outreach message."""
        msg = (
            f"Namaste! I'm Aniket from Pune. Saw *{self.name}* online — great reviews! 🙏\n\n"
            "I've built a WhatsApp bot that takes patient appointments 24×7 — "
            "no app for your patients, no new software for your staff.\n\n"
            "I'm offering a *free 30-day pilot to 3 clinics* in Pune — no card, no contract.\n\n"
            "90-sec demo 👇\nhttps://clinic-bot-web.onrender.com\n\n"
            "Would you be open to a 10-min chat this week?\n\n"
            "— Aniket | +91 7030344210"
        )
        return f"https://wa.me/{self.phone}?text={quote(msg)}"


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
