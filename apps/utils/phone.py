"""Phone-number normalization for India-focused storage.

Canonical format: 12-digit string starting with "91", no "+", no spaces.
This is what Meta's WhatsApp Cloud API uses on the wire (in wa_id and
metadata.display_phone_number) and what the bot stores everywhere.

Examples:
  "7030344210"          → "917030344210"   (10 digits → prefix 91)
  "07030344210"         → "917030344210"   (11 digits, leading 0 stripped)
  "917030344210"        → "917030344210"   (already canonical)
  "+91 7030 344 210"    → "917030344210"   (strip non-digits, then 10-digit rule)
  "+1-415-555-1234"     → ValueError       (not India / wrong length)
  ""                    → ValueError       (empty)
"""
import re

_DIGITS_RE = re.compile(r'\D')


def normalize_phone(raw: str) -> str:
    """Return canonical 12-digit India phone (e.g. "917030344210").

    Raises ValueError with a clear message if the input can't be coerced.
    """
    if raw is None:
        raise ValueError("phone number is None")
    digits = _DIGITS_RE.sub('', str(raw))
    if not digits:
        raise ValueError(f"phone number has no digits: {raw!r}")

    if len(digits) == 12 and digits.startswith('91'):
        return digits
    if len(digits) == 11 and digits.startswith('0'):
        return '91' + digits[1:]
    if len(digits) == 10:
        return '91' + digits

    raise ValueError(
        f"phone number not normalizable to 91XXXXXXXXXX: got {digits!r} "
        f"({len(digits)} digits) from input {raw!r}"
    )


def normalize_phone_safe(raw: str, default: str = '') -> str:
    """Same as normalize_phone, but returns `default` on failure instead of
    raising. Useful for non-blocking paths (e.g. observability correlation,
    webhook extract) where we'd rather skip than crash."""
    if not raw:
        return default
    try:
        return normalize_phone(raw)
    except ValueError:
        return default
