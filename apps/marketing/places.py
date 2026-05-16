"""Google Places API (New) client + scoring rules for clinic lead-gen."""
import logging
from typing import Iterable

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Fields we ask Google to return (cheaper than full payload).
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.formattedAddress",
    "places.googleMapsUri",
    "places.types",
    "places.businessStatus",
    "places.websiteUri",   # used to score "needs digital booking" (no website = strong signal)
    "nextPageToken",        # required to paginate past the first 20 results
])

# Default search queries — covers Maharashtra Tier 1 cities × multiple specialties.
# Each query returns up to 20 places. With ~24 queries below we get up to ~480
# candidates, dedupe by phone+place_id, score, and keep the top N (default 20).
#
# The query space is generated combinatorially — every {specialty} × {area} ×
# {city} — giving ~1,600 unique queries. `queries_for_today()` returns a fresh
# rotating slice each day so we never re-scrape an exhausted query. With 3-page
# pagination (60 results/query) this is years of fresh leads, not the ~265-clinic
# dead-end the old 24 fixed queries hit.

# Clinic-dense neighbourhoods per city. Add cities/areas freely — the generator
# below picks them all up.
CITY_AREAS = {
    'Pune':       ['Kothrud', 'Aundh', 'Baner', 'Viman Nagar', 'Hadapsar',
                   'Wakad', 'Hinjewadi', 'Kharadi', 'Kalyani Nagar', 'Pimpri'],
    'Mumbai':     ['Andheri', 'Bandra', 'Powai', 'Borivali', 'Dadar',
                   'Goregaon', 'Malad', 'Chembur', 'Mulund', 'Ghatkopar'],
    'Thane':      ['Thane West', 'Ghodbunder Road', 'Naupada', 'Kolshet', 'Majiwada'],
    'Nashik':     ['College Road', 'Gangapur Road', 'Indira Nagar', 'Panchavati', 'Deolali'],
    'Nagpur':     ['Dharampeth', 'Sadar', 'Civil Lines', 'Manish Nagar', 'Pratap Nagar'],
    'Bengaluru':  ['Koramangala', 'Indiranagar', 'Whitefield', 'Jayanagar',
                   'HSR Layout', 'Marathahalli', 'BTM Layout', 'Electronic City',
                   'Rajajinagar', 'Bannerghatta Road'],
    'Hyderabad':  ['Banjara Hills', 'Jubilee Hills', 'Gachibowli', 'Kukatpally',
                   'Madhapur', 'Ameerpet', 'Begumpet', 'Secunderabad'],
    'Delhi':      ['Saket', 'Rohini', 'Dwarka', 'Lajpat Nagar', 'Janakpuri',
                   'Vasant Kunj', 'Pitampura', 'Karol Bagh'],
    'Ahmedabad':  ['Satellite', 'Bopal', 'Maninagar', 'Navrangpura', 'Vastrapur', 'Bodakdev'],
    'Surat':      ['Adajan', 'Vesu', 'Athwa', 'Citylight', 'Piplod'],
    'Indore':     ['Vijay Nagar', 'Palasia', 'Sudama Nagar', 'Rau', 'Bhawarkua'],
    'Jaipur':     ['Malviya Nagar', 'Vaishali Nagar', 'C Scheme', 'Mansarovar', 'Raja Park'],
    'Chennai':    ['Anna Nagar', 'Adyar', 'Velachery', 'T Nagar', 'Porur', 'OMR'],
    'Kolkata':    ['Salt Lake', 'Ballygunge', 'Behala', 'New Town', 'Garia'],
    'Lucknow':    ['Gomti Nagar', 'Hazratganj', 'Indira Nagar', 'Aliganj'],
    'Coimbatore': ['RS Puram', 'Saibaba Colony', 'Peelamedu', 'Gandhipuram'],
}

# Specialties — small owner-operated clinic types that fit the WhatsApp-booking
# pitch. Each becomes "{specialty} clinic {area} {city}".
SPECIALTIES = [
    'physiotherapy', 'dental', 'skin', 'dermatology', 'ENT',
    'orthopedic', 'pediatric', 'eye care', 'gynaecology', 'ayurvedic',
    'homeopathy', 'dietician', 'IVF fertility', 'diabetes', 'physiotherapy rehab',
]


def generate_queries() -> list[str]:
    """Full combinatorial query list: {specialty} clinic {area} {city}.

    ~111 areas × 15 specialties ≈ 1,600 unique queries. Deterministic order
    so daily rotation in `queries_for_today()` is stable across runs.
    """
    out: list[str] = []
    for city, areas in CITY_AREAS.items():
        for area in areas:
            for spec in SPECIALTIES:
                out.append(f"{spec} clinic {area} {city}")
    return out


def queries_for_today(per_day: int = 25) -> list[str]:
    """Today's rotating slice of `generate_queries()`.

    Consecutive days get consecutive, non-overlapping slices — so each day
    explores fresh queries instead of re-scraping exhausted ones. The whole
    list cycles every ~(total / per_day) days, by which point early queries
    have fresh results (clinics open/close, Google re-ranks).
    """
    import datetime
    all_q = generate_queries()
    if per_day >= len(all_q):
        return all_q
    day_num = datetime.date.today().toordinal()
    start = (day_num * per_day) % len(all_q)
    slice_ = all_q[start:start + per_day]
    if len(slice_) < per_day:               # wrap past the end of the list
        slice_ += all_q[:per_day - len(slice_)]
    return slice_


# Back-compat: some callers still import DEFAULT_QUERIES. It now means
# "today's rotating slice" rather than a fixed 24.
DEFAULT_QUERIES = queries_for_today()


# ─── Scoring rules ───────────────────────────────────────────────

# Names containing these words are typically chains/hospitals → skip
EXCLUDE_KEYWORDS = (
    'hospital', 'multispeciality', 'multi-speciality', 'medical college',
    'apollo', 'fortis', 'medanta', 'manipal', 'ruby hall', 'jehangir',
    'narayana', 'max ', 'aiims', 'sahyadri',
)


# Indian landline STD codes for major cities — useful as an extra defense
# in case a number "looks" mobile (10 digits) but is actually a virtual
# landline routed through one of these area codes.
INDIAN_LANDLINE_STD_CODES = {
    '11',   # Delhi
    '20',   # Pune
    '22',   # Mumbai
    '33',   # Kolkata
    '40',   # Hyderabad
    '44',   # Chennai
    '79',   # Ahmedabad
    '80',   # Bengaluru
    '120',  # Noida
    '124',  # Gurgaon
    '141',  # Jaipur
    '161',  # Ludhiana
    '172',  # Chandigarh
    '253',  # Nashik
    '241',  # Ahmednagar
    '712',  # Nagpur
    '240',  # Aurangabad
}


def _is_mobile_phone(raw_phone: str) -> bool:
    """Indian mobile numbers start with 6-9 and have exactly 10 digits.

    Display formats vary: "+91 95599 16655", "095599 16655", "9559916655",
    "020 12345678" (landline). Strip everything except digits, drop the
    country code (91) and any leading 0, then check the 10-digit form starts
    with 6-9 AND doesn't begin with a known landline STD area code.

    WhatsApp Business API can only message true mobile numbers — landlines
    return delivery errors. Better to filter them out at lead-gen time than
    burn outreach attempts on dead numbers.
    """
    digits = ''.join(c for c in (raw_phone or '') if c.isdigit())
    if not digits:
        return False
    # Strip 91 country code prefix
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    # Strip leading 0 (Indian display convention for both landline + mobile)
    if len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    # Must be exactly 10 digits starting with 6, 7, 8, or 9
    if len(digits) != 10 or digits[0] not in '6789':
        return False
    # Defense-in-depth: even if 10-digits-starting-with-6-9, reject if it
    # matches a known landline area-code prefix (some virtual / VoIP numbers
    # pretend to be mobile but route to landlines).
    for std in INDIAN_LANDLINE_STD_CODES:
        if digits.startswith(std):
            return False
    return True


def _score(place: dict) -> int:
    """Higher = stronger fit for owner-operated clinic pilot.

    Tuned for high conversion rate — score >= 12 is the keeper threshold.
    """
    name = (place.get('displayName', {}).get('text') or '').lower()
    types = place.get('types') or []
    rating = place.get('rating') or 0
    reviews = place.get('userRatingCount') or 0
    status = place.get('businessStatus') or ''
    phone_raw = place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber') or ''

    if status != 'OPERATIONAL':
        return -100

    # Hard exclusions first — chains, hospitals, multi-speciality
    for kw in EXCLUDE_KEYWORDS:
        if kw in name:
            return -100   # never save these

    # Phone gate: only mobile-numbered clinics (owner-operated proxy)
    if not _is_mobile_phone(phone_raw):
        return -100

    score = 0

    # Review band — narrow sweet spot for owner-operated, established but small
    if 150 <= reviews <= 350:
        score += 10
    elif 100 <= reviews < 150:
        score += 7
    elif 350 < reviews <= 500:
        score += 5
    elif 50 <= reviews < 100:
        score += 2
    elif reviews > 500:
        score -= 5
    else:
        score -= 5   # < 50 reviews = unproven business

    # Rating — only well-rated clinics
    if 4.6 <= rating <= 4.9:
        score += 5
    elif 4.4 <= rating < 4.6:
        score += 2
    elif rating < 4.3:
        score -= 10

    # Specialty match
    if 'physiotherapist' in types:
        score += 5
    elif 'dentist' in types:
        score += 4
    elif 'dermatologist' in types:
        score += 3
    elif 'doctor' in types:
        score += 1
    else:
        score -= 3

    # Single-location / branding signals
    if 'branch' in name or 'centers' in name:
        score -= 3   # likely chain
    if any(w in name for w in [' dr.', 'dr ', 'dr.']) or name.startswith('dr'):
        score += 2   # owner-named clinic

    # ─── "Needs digital booking" signal ──────────────────────────
    # A clinic with NO website is low-tech. The more reviews it has, the more
    # patient volume — and the more bookings it's losing to missed calls and
    # phone-tag. A busy clinic with no website is the single best fit for a
    # WhatsApp booking bot: high need, no incumbent system to displace.
    has_website = bool(place.get('websiteUri'))
    if not has_website:
        if reviews >= 100:
            score += 8   # busy + no digital presence → ideal customer
        else:
            score += 3   # low-tech, smaller — still a fit
    # A clinic that already has a website has *some* digital booking already;
    # mild deprioritisation (not exclusion — many sites have no booking).
    elif reviews >= 100:
        score -= 1

    return score


# Keeper threshold — only leads scoring at or above this are saved as a Lead.
# Tuned with the rules above so a typical "owner-operated Pune physio with 200
# reviews and rating 4.7 on a mobile number" lands at ~22 (well above 12).
SCORE_THRESHOLD = 12


# ─── API client ──────────────────────────────────────────────────

class PlacesAPIError(Exception):
    pass


def search_text(query: str, max_pages: int = 3) -> list:
    """Text Search for `query`, paginating up to `max_pages` (20 results each).

    The old code fetched only the first 20 of up to 60 available results —
    throwing away two-thirds of every query. We now follow `nextPageToken`
    for the full set. Returns the combined raw `places` list.
    """
    api_key = getattr(settings, 'GOOGLE_PLACES_API_KEY', '') \
        or __import__('os').environ.get('GOOGLE_PLACES_API_KEY', '')
    if not api_key:
        raise PlacesAPIError("GOOGLE_PLACES_API_KEY is not set in settings or env")

    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': api_key,
        'X-Goog-FieldMask': FIELD_MASK,
    }

    all_places: list = []
    page_token = None
    for _page in range(max(1, max_pages)):
        body = {
            'textQuery': query,
            'maxResultCount': 20,
            'languageCode': 'en',
            'regionCode': 'IN',
        }
        if page_token:
            body['pageToken'] = page_token
        try:
            resp = requests.post(PLACES_TEXT_SEARCH_URL, json=body, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise PlacesAPIError(f"Network error: {e}") from e
        if resp.status_code != 200:
            raise PlacesAPIError(
                f"Places API returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        all_places.extend(data.get('places', []))
        page_token = data.get('nextPageToken')
        if not page_token:
            break   # no more pages

    return all_places


def score_and_dedupe(places: Iterable[dict]) -> list[tuple[int, dict]]:
    """Score each place and remove duplicates (by Place ID)."""
    seen: set[str] = set()
    scored: list[tuple[int, dict]] = []
    for place in places:
        pid = place.get('id')
        if not pid or pid in seen:
            continue
        # Skip places without phone number (we can't WhatsApp them)
        if not place.get('nationalPhoneNumber') and not place.get('internationalPhoneNumber'):
            continue
        seen.add(pid)
        scored.append((_score(place), place))
    scored.sort(reverse=True, key=lambda t: t[0])
    return scored
