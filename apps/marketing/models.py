import secrets
from urllib.parse import quote

from django.conf import settings
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

    # ─── Personalised-outreach tracking ──────────────────────────
    slug = models.CharField(
        max_length=12, unique=True, db_index=True, blank=True,
        help_text="Random hex used in the personalised landing URL /p/<slug>/",
    )
    engaged_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text="First time the prospect opened their personalised landing page",
    )
    last_visited_at = models.DateTimeField(null=True, blank=True)
    visit_count = models.PositiveIntegerField(default=0)
    ai_followup_draft = models.TextField(
        blank=True,
        help_text="Most recent AI-drafted follow-up message (Groq); operator reviews then sends",
    )
    last_followup_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Last time the operator clicked a follow-up template button — "
                  "used to suppress action pill during the cooldown period.",
    )
    last_followup_template = models.CharField(
        max_length=40, blank=True,
        help_text="Which template was used for the most recent follow-up "
                  "(engaged / 3day / 7day / replied_silent).",
    )

    class Meta:
        ordering = ['-score', '-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            for _ in range(8):
                candidate = secrets.token_hex(5)  # 10 chars
                if not Lead.objects.filter(slug=candidate).exists():
                    self.slug = candidate
                    break
        super().save(*args, **kwargs)

    @property
    def is_mobile_phone(self) -> bool:
        """True if this lead's phone is a true Indian mobile (not a landline).

        Used by admin UI + cleanup command to flag/remove leads we can't
        reach via WhatsApp.
        """
        from apps.marketing.places import _is_mobile_phone
        return _is_mobile_phone(self.phone)

    # ─── Auto-detect "needs follow-up" status ──────────────────────
    #
    # Returns a dict with the recommended action OR None if no follow-up
    # is needed (e.g., not yet contacted, already converted, or recently
    # active conversation).
    #
    # Used by the admin list to show "🎯 Action" column + the drawer to
    # auto-highlight the right template button.

    # Cooldown after a follow-up is sent — don't surface another action pill
    # until this many days have passed (gives the prospect time to respond).
    FOLLOWUP_COOLDOWN_DAYS = 3

    def followup_status(self) -> dict | None:
        from datetime import timedelta
        from django.utils import timezone

        # Never follow-up these statuses
        if self.status in ('new', 'pilot', 'demo_booked', 'not_interested', 'invalid'):
            # 'new' = not yet contacted; rest = closed-out states
            return None

        now = timezone.now()

        # Cooldown: if a follow-up was sent recently, hide the action pill
        # until cooldown expires (so the operator isn't nagged to re-send
        # the same template moments after sending it).
        if self.last_followup_at:
            days_since_followup = (now - self.last_followup_at).days
            if days_since_followup < self.FOLLOWUP_COOLDOWN_DAYS:
                return None

        contacted = self.contacted_at or self.created_at
        if not contacted:
            return None
        days_since_contact = (now - contacted).days

        engaged = self.engaged_at is not None
        last_visit = self.last_visited_at

        # ─── HOT: replied + visited recently → use the conversation template
        if self.status == 'replied' and last_visit:
            hours_since_visit = (now - last_visit).total_seconds() / 3600
            if hours_since_visit < 48:
                return {
                    'urgency': 'hot',
                    'emoji': '🔥',
                    'label': f'Active — visited {self._humanize(now - last_visit)} ago',
                    'template': 'followup_replied_silent_link',
                    'template_label': 'Reply (3 demo options)',
                }

        # ─── HOT: opened the personalised page but didn't reply yet
        if engaged and self.status == 'sent':
            visits = self.visit_count or 1
            return {
                'urgency': 'hot',
                'emoji': '🔥',
                'label': f'Opened page · {visits}× visit{"s" if visits > 1 else ""}',
                'template': 'followup_engaged_link',
                'template_label': 'Engaged but silent',
            }

        # ─── MEDIUM: replied but quiet for 3+ days → 'Replied but silent' template
        if self.status == 'replied' and days_since_contact >= 3:
            return {
                'urgency': 'medium',
                'emoji': '💬',
                'label': f'Replied but silent ({days_since_contact}d)',
                'template': 'followup_replied_silent_link',
                'template_label': 'Replied but silent',
            }

        # ─── MEDIUM: sent 3-7 days ago, no engagement → 3-day soft ping
        if self.status == 'sent' and 3 <= days_since_contact <= 6:
            return {
                'urgency': 'medium',
                'emoji': '📩',
                'label': f'No reply ({days_since_contact}d) — try 3-day ping',
                'template': 'followup_3day_link',
                'template_label': '3-day soft ping',
            }

        # ─── LOW: sent 7-14 days ago, no engagement → 7-day final ping
        if self.status == 'sent' and 7 <= days_since_contact <= 14:
            return {
                'urgency': 'low',
                'emoji': '⏰',
                'label': f'Quiet ({days_since_contact}d) — final ping',
                'template': 'followup_7day_link',
                'template_label': '7-day final ping',
            }

        # ─── COLD: sent >14 days ago, no engagement → consider archiving
        if self.status == 'sent' and days_since_contact > 14:
            return {
                'urgency': 'cold',
                'emoji': '❄️',
                'label': f'Cold ({days_since_contact}d) — consider archiving',
                'template': 'followup_7day_link',
                'template_label': '7-day final ping',
            }

        return None

    @staticmethod
    def _humanize(td) -> str:
        secs = int(td.total_seconds())
        if secs < 60:
            return f'{secs}s'
        if secs < 3600:
            return f'{secs // 60}m'
        if secs < 86400:
            return f'{secs // 3600}h'
        return f'{secs // 86400}d'

    def __str__(self):
        return f"[{self.get_status_display()}] {self.name} ({self.phone})"

    # ─── Outreach helpers ────────────────────────────────────────

    @property
    def landing_url(self) -> str:
        """Public, prospect-specific landing page URL.

        Uses MARKETING_PUBLIC_HOST (settable via env) and falls back to the
        production custom domain so wa.me messages always carry the branded URL.
        """
        host = getattr(settings, 'MARKETING_PUBLIC_HOST', '') \
               or 'https://docping.in'
        return f"{host.rstrip('/')}/p/{self.slug or 'demo'}/"

    @property
    def whatsapp_link(self) -> str:
        """Pre-filled wa.me link with the standard outreach message."""
        msg = (
            f"Hello! I'm Aniket. Saw *{self.name}* online — great reviews! 🙏\n\n"
            "I've built a WhatsApp bot that takes patient appointments 24×7 — "
            "no app for your patients, no new software for your staff.\n\n"
            "Put together a quick page just for your clinic 👇\n"
            f"{self.landing_url}\n\n"
            "Offering a *free 30-day pilot* — no card, no contract.\n\n"
            "Open to a 10-min chat this week?"
        )
        return f"https://wa.me/{self.phone}?text={quote(msg)}"

    # ─── Follow-up templates (used when prospect doesn't reply) ────────
    #
    # Each template self-introduces because some clinics use WhatsApp
    # disappearing-messages — they may not see the original pitch anymore.
    # Always re-attach the personalised page URL so they have one click to
    # rediscover the offer.

    def _wa_url(self, msg: str) -> str:
        return f"https://wa.me/{self.phone}?text={quote(msg)}"

    @property
    def followup_engaged_link(self) -> str:
        """Best opener if they OPENED the personalised page but didn't reply
        (high-intent — give them the numbers they came for)."""
        msg = (
            f"Hey {self.name}, Aniket from *DocPing* here. 🙏\n\n"
            "Saw you checked out the page I sent — wanted to make sure you "
            "had what you needed.\n\n"
            f"Quick recap — DocPing is a WhatsApp bot that books patient "
            f"appointments 24×7. For a clinic your size "
            f"(~{self.estimated_calls_per_day} booking calls/day), the math is:\n\n"
            f"  • ~30% of calls go missed after-hours\n"
            f"  • That's ~₹{self.estimated_monthly_recovery:,}/month in lost bookings\n"
            f"  • DocPing recovers them at ₹999/month\n\n"
            "Page still live 👇\n"
            f"{self.landing_url}\n\n"
            "10-min call this week? Happy to share what'd actually help."
        )
        return self._wa_url(msg)

    @property
    def followup_3day_link(self) -> str:
        """3 days quiet — no engagement signal. Re-introduce + soft nudge."""
        msg = (
            f"Hey {self.name}! 🙏\n\n"
            "Aniket here — pinged you a few days back about *DocPing*, the "
            "WhatsApp appointment-booking bot for clinics.\n\n"
            "(Sharing again in case the earlier message disappeared — some "
            "WhatsApp settings auto-delete after a day.)\n\n"
            "Short version: patients book in 4 taps, your front desk doesn't "
            "lift a finger. Free 30-day pilot, no card, no contract.\n\n"
            f"Custom page for your clinic 👇\n{self.landing_url}\n\n"
            "Worth a 10-min look? Reply 'yes' or 'later' and I'll respect either."
        )
        return self._wa_url(msg)

    @property
    def followup_7day_link(self) -> str:
        """7-10 days quiet — final polite ping, value-first angle, low-pressure exit."""
        msg = (
            f"Hi {self.name}, Aniket from *DocPing* one last time. 🙏\n\n"
            "If WhatsApp booking isn't a fit for your clinic right now, totally "
            "understand — happy to leave you alone.\n\n"
            "If you ARE curious, here's what 3 clinics on the pilot are "
            "saying after week 1:\n\n"
            "  ✅ \"Front desk saved 2 hrs/day on phone calls\"\n"
            "  ✅ \"Recovered 4 missed bookings in week 1\"\n"
            "  ✅ \"Patients love the Hindi/Marathi flow\"\n\n"
            f"Page still live 👇\n{self.landing_url}\n\n"
            "Just reply 'not now' if you want me to stop, or 'tell me more' "
            "if you're game."
        )
        return self._wa_url(msg)

    @property
    def followup_replied_silent_link(self) -> str:
        """They replied once then went silent. Pick up where you left off."""
        msg = (
            f"Hey {self.name}! 👋\n\n"
            "Aniket — picking up from our last chat about *DocPing*.\n\n"
            "Wanted to make it easy for you to decide. Three ways to see it:\n\n"
            "1️⃣  Try the bot yourself (30 sec) — message *+1 555 177 3718* with 'Hi'\n"
            "2️⃣  Watch the demos on our home page — https://docping.in\n"
            "3️⃣  10-min Zoom call where I walk you through it\n\n"
            f"Custom page for {self.name}: {self.landing_url}\n\n"
            "Free 30-day pilot is still open. Pick one and we'll move forward."
        )
        return self._wa_url(msg)

    # ─── Specialty inference (for landing personalisation) ─────

    SPECIALTY_KEYWORDS = (
        ('physiotherapist', 'physio'),
        ('physical_therapy', 'physio'),
        ('dentist',         'dental'),
        ('dental_clinic',   'dental'),
        ('chiropractor',    'chiro'),
        ('orthopedic',      'ortho'),
        ('gynecologist',    'gynae'),
        ('pediatrician',    'paeds'),
        ('dermatologist',   'derm'),
        ('hospital',        'general'),
        ('doctor',          'general'),
    )

    @property
    def specialty(self) -> str:
        """Best-effort specialty key inferred from Google Place types.

        Returns one of: physio / dental / chiro / ortho / gynae / paeds / derm
        / general / clinic (default).
        """
        types = (self.types or '').lower()
        name = (self.name or '').lower()
        for needle, label in self.SPECIALTY_KEYWORDS:
            if needle in types or needle in name:
                return label
        return 'clinic'

    @property
    def estimated_calls_per_day(self) -> int:
        """Rough heuristic: review count → daily booking calls.

        Most clinics get a Google review for ~1 in 25 patient interactions.
        Reviews accumulate over years (assume ~24 months active history).
        Return is a conservative integer ≥ 3.
        """
        if not self.reviews:
            return 5
        monthly = self.reviews / 24
        # 1 review per ~25 interactions → daily calls ≈ monthly_reviews * 25 / 30
        per_day = round(monthly * 25 / 30)
        return max(3, min(per_day, 40))

    @property
    def estimated_monthly_recovery(self) -> int:
        """Rupees recoverable per month if our bot captures missed bookings.

        Assumes ~30% of booking calls are missed (after-hours, holds, busy)
        and avg consultation revenue ₹500.
        """
        missed_per_day = max(1, round(self.estimated_calls_per_day * 0.3))
        return missed_per_day * 500 * 30  # 30 days


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


class DashboardConfig(models.Model):
    """Singleton row holding tunable assumptions for the admin dashboard.

    Only ever one row (pk=1, enforced in save()). Edit the fields from the
    admin to update pipeline-value math + goal targets without redeploying.
    """
    arpu_inr = models.PositiveIntegerField(
        default=2000,
        help_text="Assumed monthly revenue per converted clinic (₹). Used by the pipeline-value hero.",
    )

    # Industry-benchmark fallbacks for conversion rates. Used until your
    # observed funnel has at least `min_sample_size` leads at that stage.
    benchmark_new_to_sent_pct = models.PositiveSmallIntegerField(
        default=80, help_text="Default % of new leads we expect to contact."
    )
    benchmark_sent_to_replied_pct = models.PositiveSmallIntegerField(
        default=15, help_text="Default % of sent leads expected to reply."
    )
    benchmark_replied_to_demo_pct = models.PositiveSmallIntegerField(
        default=40, help_text="Default % of replied leads that book a demo."
    )
    benchmark_demo_to_pilot_pct = models.PositiveSmallIntegerField(
        default=50, help_text="Default % of demos that convert to a paid pilot."
    )

    min_sample_size = models.PositiveSmallIntegerField(
        default=10,
        help_text=(
            "Switch from benchmark to observed conversion at this stage once "
            "you have this many leads at that stage. Lower = trust your data "
            "earlier (noisier); higher = stick with benchmarks longer."
        ),
    )

    # Weekly / monthly goals shown as progress bars on the dashboard.
    goal_outreach_per_week = models.PositiveIntegerField(default=50)
    goal_demos_per_week    = models.PositiveIntegerField(default=3)
    goal_pilots_per_month  = models.PositiveIntegerField(default=2)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dashboard config"
        verbose_name_plural = "Dashboard config"

    def __str__(self):
        return f"Dashboard config (ARPU ₹{self.arpu_inr}, demo goal {self.goal_demos_per_week}/wk)"

    def save(self, *args, **kwargs):
        # Singleton: always pk=1, never create a second row.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'DashboardConfig':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WebPushSettings(models.Model):
    """Singleton holding the project's VAPID keys + contact email.

    Generated lazily on first access — see `load()`. Stored in the DB so the
    operator never has to mess with env vars; same singleton pattern as
    DashboardConfig.

    NEVER rotate the private key once subscribers exist — old subscriptions
    will silently break. If you ever do rotate, also clear PushSubscription.
    """
    vapid_public_key = models.TextField(blank=True)
    vapid_private_key = models.TextField(blank=True)
    contact_email = models.EmailField(
        default='ops@docping.in',
        help_text=(
            "Required by the Web Push standard — push services use this to "
            "contact you if your pushes are misbehaving. Anything you check."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Web push settings"
        verbose_name_plural = "Web push settings"

    def __str__(self):
        return f"WebPush keys (set: {bool(self.vapid_public_key)})"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'WebPushSettings':
        obj, created = cls.objects.get_or_create(pk=1)
        if not obj.vapid_public_key or not obj.vapid_private_key:
            obj._mint_keys()
            obj.save()
        return obj

    def _mint_keys(self):
        """Generate a fresh VAPID key pair using py-vapid. Called once on
        first access; the keys persist forever afterwards."""
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        # py-vapid serialises keys as PEM strings via these helpers
        from cryptography.hazmat.primitives import serialization
        priv_pem = v.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode('ascii')
        # Public key as raw 65-byte uncompressed point, then base64url
        # (the format browsers expect for `applicationServerKey`).
        pub_raw = v.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        import base64
        pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b'=').decode('ascii')
        self.vapid_private_key = priv_pem
        self.vapid_public_key = pub_b64


class PushSubscription(models.Model):
    """One row per browser/device a user has opted in from.

    A single User can have many subscriptions (laptop Chrome, mobile Chrome,
    home-screen PWA). Each carries the FCM/APNS endpoint + the keys we need
    to encrypt payloads.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='push_subscriptions',
    )
    endpoint = models.URLField(max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=120)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    fail_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_id} · {self.user_agent[:60]}"

    @property
    def as_payload(self) -> dict:
        """Shape pywebpush expects."""
        return {
            'endpoint': self.endpoint,
            'keys': {'p256dh': self.p256dh, 'auth': self.auth},
        }
