"""Web push notification glue.

Wraps `pywebpush` so the rest of the app sends notifications by calling
`notify_user(user, title, body, **opts)` and never has to touch keys,
encryption, or the FCM/APNS endpoint.

Architecture summary (see also: docs in apps/marketing/models.py):
  • VAPID keys + contact email live in WebPushSettings (singleton, auto-minted
    on first access — no env vars).
  • Each operator browser/device is a PushSubscription row.
  • notify_user() fans out to every subscription for that user, prunes any
    that the push service rejects with 404/410 (subscriber unsubscribed
    via system settings / cleared site data).
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from django.contrib.auth import get_user_model
from django.utils import timezone

logger = logging.getLogger(__name__)

User = get_user_model()


def _settings():
    from .models import WebPushSettings
    return WebPushSettings.load()


def public_vapid_key() -> str:
    """Base64url-encoded public key — the value the JS subscribe call needs."""
    return _settings().vapid_public_key


def send_push(subscription, title: str, body: str, *, url: str = '/admin/',
              tag: str = 'docping', icon: str | None = None) -> bool:
    """Deliver one notification to one PushSubscription. Returns True on
    success. Marks the subscription failed (and prunes if the push service
    says it's permanently gone) on error.
    """
    from pywebpush import webpush, WebPushException
    s = _settings()
    if not s.vapid_private_key:
        logger.warning("[push] No VAPID private key — refusing to send.")
        return False

    payload = json.dumps({
        'title': title,
        'body': body,
        'url': url,
        'tag': tag,
        'icon': icon or '/static/marketing/brand/docping-icon.svg',
        'badge': '/static/marketing/brand/docping-icon.svg',
    })

    # pywebpush 2.x calls Vapid.from_string() on a raw string arg, which
    # expects a base64-encoded private key — not the PEM we generate via
    # py-vapid. Pre-build the Vapid object via from_pem() and pass that;
    # pywebpush detects the instance and skips the broken decode path.
    from py_vapid import Vapid
    try:
        vapid_obj = Vapid.from_pem(s.vapid_private_key.encode('utf-8'))
    except Exception as exc:
        logger.exception("[push] Failed to load VAPID private key: %s", exc)
        return False

    try:
        webpush(
            subscription_info=subscription.as_payload,
            data=payload,
            vapid_private_key=vapid_obj,
            vapid_claims={'sub': f"mailto:{s.contact_email}"},
        )
        subscription.last_used_at = timezone.now()
        subscription.fail_count = 0
        subscription.save(update_fields=['last_used_at', 'fail_count'])
        return True
    except WebPushException as exc:
        status = getattr(exc.response, 'status_code', None)
        # 404/410: subscription is gone (user uninstalled / cleared site data).
        if status in (404, 410):
            logger.info("[push] Pruning dead subscription %s (status %s)",
                        subscription.pk, status)
            subscription.delete()
            return False
        # Anything else: keep the row but bump fail_count.
        subscription.last_failed_at = timezone.now()
        subscription.fail_count = (subscription.fail_count or 0) + 1
        subscription.save(update_fields=['last_failed_at', 'fail_count'])
        logger.warning("[push] webpush failed (%s): %s", status, exc)
        return False
    except Exception as exc:
        logger.exception("[push] unexpected webpush error: %s", exc)
        return False


def notify_user(user, title: str, body: str, **opts) -> int:
    """Fan out to every PushSubscription belonging to `user`.
    Returns the number of pushes that succeeded."""
    from .models import PushSubscription
    if user is None:
        return 0
    subs = PushSubscription.objects.filter(user=user)
    sent = 0
    for s in subs:
        if send_push(s, title, body, **opts):
            sent += 1
    return sent


def notify_all_staff(title: str, body: str, **opts) -> int:
    """Fan out to every staff user with a subscription. Used for events
    that any operator should know about (hot lead engagement, stuck-lead
    digest, etc.)."""
    from .models import PushSubscription
    sent = 0
    for s in PushSubscription.objects.select_related('user').filter(user__is_staff=True):
        if send_push(s, title, body, **opts):
            sent += 1
    return sent
