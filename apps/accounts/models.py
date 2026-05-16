from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Project-wide custom user.

    Holds the two WhatsApp numbers shown on the public landing page, stored
    directly on the user row so the superuser edits them inside their own
    admin form — no separate settings model.
    """
    bot_number = models.CharField(
        max_length=20, blank=True,
        help_text="Digits only with country code. E.g. 15551773718 (Meta test bot). "
                  "Used for 'Try the bot' CTAs on the landing page.",
    )
    contact_number = models.CharField(
        max_length=20, blank=True,
        help_text="Digits only with country code. Your personal WhatsApp for enquiries. "
                  "Used for 'Talk to me' CTAs on the landing page.",
    )
    contact_name = models.CharField(
        max_length=80, blank=True,
        help_text="First name shown in CTA copy (e.g. \"Chat with Aniket\"). "
                  "Leave blank to fall back to the account's first_name/username.",
    )
    official_mail = models.EmailField(
        blank=True,
        help_text="Public DocPing email shown on the landing page and the "
                  "legal pages (Privacy / Terms / Data Deletion), e.g. "
                  "info@docping.in. Leave blank to fall back to this "
                  "account's login email.",
    )

    # Helpers so templates always receive a clean digits-only string.
    @property
    def clean_bot_number(self) -> str:
        return (self.bot_number or '').lstrip('+').replace(' ', '')

    @property
    def clean_contact_number(self) -> str:
        return (self.contact_number or '').lstrip('+').replace(' ', '')

    @property
    def landing_display_name(self) -> str:
        return self.contact_name or self.first_name or self.username

    @property
    def public_email(self) -> str:
        """Email shown on public pages — the official mailbox, falling back to
        the account's login email so legal pages never render a blank address."""
        return (self.official_mail or '').strip() or (self.email or '').strip()
