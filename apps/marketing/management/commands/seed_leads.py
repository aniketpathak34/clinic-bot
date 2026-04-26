"""Pull fresh clinic leads from Google Places API, score them, save the top N.

  python manage.py seed_leads               # default: 20 new leads
  python manage.py seed_leads --top 30      # save top 30
  python manage.py seed_leads --query "dental clinic Aundh Pune"   # one custom query
  python manage.py seed_leads --dry-run     # log what we'd save, write nothing

Idempotent — already-stored phone numbers are skipped, so re-running daily
just appends fresh prospects to the Lead table.
"""
from django.core.management.base import BaseCommand

from apps.marketing.models import Lead
from apps.marketing.places import (
    DEFAULT_QUERIES,
    PlacesAPIError,
    SCORE_THRESHOLD,
    score_and_dedupe,
    search_text,
)


def _norm_phone(place: dict) -> str:
    """Return digits-only phone with country code (defaults to 91 for IN numbers)."""
    raw = place.get('internationalPhoneNumber') or place.get('nationalPhoneNumber') or ''
    digits = ''.join(c for c in raw if c.isdigit())
    if not digits:
        return ''
    if not raw.startswith('+') and digits.startswith('0'):
        digits = digits[1:]   # strip leading 0
    if not digits.startswith('91'):
        digits = '91' + digits
    return digits


class Command(BaseCommand):
    help = "Fetch clinic leads from Google Places API, score them, save the top N as Lead rows."

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=10,
                            help='Max number of new leads to save (default 10).')
        parser.add_argument('--query', type=str, default='',
                            help='Custom single query instead of the default Pune set.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print what would be saved, write nothing.')
        parser.add_argument('--min-score', type=int, default=SCORE_THRESHOLD,
                            help=f'Only save leads scoring >= this (default {SCORE_THRESHOLD}).')

    def handle(self, *args, **options):
        top_n = options['top']
        custom_query = options['query'].strip()
        dry_run = options['dry_run']
        min_score = options['min_score']

        queries = [custom_query] if custom_query else DEFAULT_QUERIES

        all_places: list[dict] = []
        for q in queries:
            try:
                self.stdout.write(f"  → {q}")
                results = search_text(q, max_results=20)
                self.stdout.write(self.style.SUCCESS(f"     {len(results)} results"))
                all_places.extend(results)
            except PlacesAPIError as e:
                self.stderr.write(self.style.ERROR(f"     FAILED: {e}"))

        scored = score_and_dedupe(all_places)
        self.stdout.write(f"\nTotal unique candidates: {len(scored)}")

        # Skip leads that are already in DB by phone number
        existing_phones = set(Lead.objects.values_list('phone', flat=True))
        existing_place_ids = set(Lead.objects.exclude(place_id='').values_list('place_id', flat=True))

        saved, skipped, below_threshold = 0, 0, 0
        for score, place in scored:
            if saved >= top_n:
                break
            if score < min_score:
                below_threshold += 1
                continue
            phone = _norm_phone(place)
            place_id = place.get('id', '')
            if not phone:
                continue
            if phone in existing_phones or place_id in existing_place_ids:
                skipped += 1
                continue

            name = place.get('displayName', {}).get('text', 'Unknown')
            address = place.get('formattedAddress', '')[:300]
            rating = place.get('rating') or None
            reviews = place.get('userRatingCount') or 0
            types_csv = ','.join(place.get('types') or [])
            maps_url = place.get('googleMapsUri', '')

            tag = '[DRY] ' if dry_run else ''
            self.stdout.write(
                f"  {tag}+ score={score:>3}  {name[:50]}  {phone}  ★{rating} ({reviews})"
            )

            if not dry_run:
                Lead.objects.create(
                    name=name,
                    phone=phone,
                    address=address,
                    rating=rating,
                    reviews=reviews,
                    types=types_csv,
                    google_maps_url=maps_url,
                    place_id=place_id,
                    score=score,
                )
            saved += 1
            existing_phones.add(phone)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"Done — {saved} new leads saved, {skipped} duplicates skipped, "
            f"{below_threshold} below score threshold ({min_score})"
            + (' (DRY RUN — nothing written)' if dry_run else '')
        ))
