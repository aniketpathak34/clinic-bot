"""Backend for the redesigned admin home — the 'war room'.

Three pieces:
  • dashboard_metrics() — hero numbers, funnel counts, sparklines, next moves
  • ai_briefing_view   — Groq-generated paragraph summarising the day
  • engagement_pulse_view — JSON poll endpoint for live "lead is on the page"
                            toasts on the dashboard
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.marketing.models import Lead


FUNNEL_STAGES = ('new', 'sent', 'replied', 'demo_booked', 'pilot', 'not_interested', 'invalid')


def _funnel_counts() -> dict[str, int]:
    """One query: status → count."""
    rows = Lead.objects.values('status').annotate(c=Count('id'))
    out = {s: 0 for s in FUNNEL_STAGES}
    for r in rows:
        out[r['status']] = r['c']
    return out


def _stage_rates(funnel: dict[str, int], cfg) -> dict:
    """Per-stage transition rate, observed from the funnel when sample is
    large enough, otherwise the benchmark from `cfg`. Returns probabilities
    in [0, 1] keyed by transition.

    Observed rates are computed from the *cumulative* funnel — i.e. how many
    leads have made it past each stage. If you have 0 demos but 3 replies,
    the demo→pilot transition has zero data, so it falls back.
    """
    # Cumulative — at each stage, the lead has reached at least that level.
    past_new     = funnel['sent'] + funnel['replied'] + funnel['demo_booked'] + funnel['pilot']
    past_sent    = funnel['replied'] + funnel['demo_booked'] + funnel['pilot']
    past_replied = funnel['demo_booked'] + funnel['pilot']
    past_demo    = funnel['pilot']

    sent_pool    = funnel['sent'] + past_sent       # everyone who was ever 'sent' or further
    replied_pool = funnel['replied'] + past_replied
    demo_pool    = funnel['demo_booked'] + past_demo
    new_pool     = funnel['new'] + past_new

    threshold = cfg.min_sample_size

    def pick(observed_num, observed_den, benchmark_pct, transition_label):
        if observed_den >= threshold:
            return {
                'value': (observed_num / observed_den) if observed_den else 0.0,
                'mode': 'observed',
                'sample': observed_den,
                'transition': transition_label,
            }
        return {
            'value': benchmark_pct / 100.0,
            'mode': 'benchmark',
            'sample': observed_den,
            'needs': threshold - observed_den,
            'transition': transition_label,
        }

    return {
        'new_to_sent':     pick(past_new,     new_pool,     cfg.benchmark_new_to_sent_pct,     'new → sent'),
        'sent_to_replied': pick(past_sent,    sent_pool,    cfg.benchmark_sent_to_replied_pct, 'sent → replied'),
        'replied_to_demo': pick(past_replied, replied_pool, cfg.benchmark_replied_to_demo_pct, 'replied → demo'),
        'demo_to_pilot':   pick(past_demo,    demo_pool,    cfg.benchmark_demo_to_pilot_pct,   'demo → pilot'),
    }


def _prob_to_pilot_by_stage(rates: dict) -> dict[str, float]:
    """Chain the per-stage transition rates into 'P(reach pilot)' from each
    current stage. A lead in 'new' has to clear 4 transitions; one in 'demo'
    only has to clear the last."""
    p1 = rates['new_to_sent']['value']
    p2 = rates['sent_to_replied']['value']
    p3 = rates['replied_to_demo']['value']
    p4 = rates['demo_to_pilot']['value']
    return {
        'new':            p1 * p2 * p3 * p4,
        'sent':           p2 * p3 * p4,
        'replied':        p3 * p4,
        'demo_booked':    p4,
        'pilot':          1.0,
        'not_interested': 0.0,
        'invalid':        0.0,
    }


def _pipeline_value(funnel: dict[str, int], cfg, rates: dict) -> int:
    """Expected MRR (₹) = Σ(count × P(reach pilot from stage)) × ARPU."""
    p_pilot = _prob_to_pilot_by_stage(rates)
    return int(sum(funnel.get(s, 0) * p_pilot.get(s, 0) for s in FUNNEL_STAGES) * cfg.arpu_inr)


def _last_n_days_lead_counts(n: int = 14) -> list[int]:
    """Sparkline-friendly list of new-lead counts per day, oldest → newest."""
    today = date.today()
    rows = (
        Lead.objects
        .filter(created_at__date__gte=today - timedelta(days=n - 1))
        .extra(select={'d': "date(created_at)"})
        .values('d').annotate(c=Count('id'))
    )
    by_day = {r['d']: r['c'] for r in rows}
    out = []
    for i in range(n):
        d = today - timedelta(days=n - 1 - i)
        # SQLite returns string, Postgres returns date — normalise to str
        key = d.isoformat() if isinstance(next(iter(by_day), ''), str) else d
        out.append(by_day.get(key, 0))
    return out


def _next_moves() -> list[dict]:
    """The three concrete actions the founder should take RIGHT NOW.

    Picked by urgency: hot follow-ups → engaged-not-replied → fresh leads to
    contact → fallback "all caught up".
    """
    moves = []
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    hot_engaged = (
        Lead.objects
        .filter(last_visited_at__gte=hour_ago)
        .exclude(status__in=('not_interested', 'invalid', 'pilot'))
        .order_by('-last_visited_at')[:1]
    )
    for lead in hot_engaged:
        moves.append({
            'tone': 'hot',
            'emoji': '🔥',
            'title': f"{lead.name} is on their page right now",
            'sub': "Strike while warm — open the drawer",
            'href': f"?_drawer={lead.pk}",
        })

    # Aggregate stuck leads needing a follow-up
    pending = []
    for lead in Lead.objects.exclude(status__in=('pilot', 'not_interested', 'invalid')).iterator():
        a = lead.followup_status()
        if a and a.get('urgency') == 'hot':
            pending.append((lead, a))
        if len(pending) >= 3:
            break
    if pending:
        n = len(pending)
        moves.append({
            'tone': 'amber',
            'emoji': '📲',
            'title': f"{n} hot follow-up{'s' if n != 1 else ''} ready to send",
            'sub': "Open the queue and clear them in 5 min",
            'href': "/admin/marketing/lead/?needs_followup=1",
        })

    # Fresh leads not yet contacted today
    new_today = Lead.objects.filter(
        status='new',
        created_at__date=date.today(),
    ).count()
    if new_today and len(moves) < 3:
        moves.append({
            'tone': 'cyan',
            'emoji': '🌱',
            'title': f"{new_today} fresh lead{'s' if new_today != 1 else ''} from today",
            'sub': "First-touch them while they're top of mind",
            'href': "/admin/marketing/lead/?status__exact=new",
        })

    if not moves:
        moves.append({
            'tone': 'dim',
            'emoji': '✨',
            'title': "All caught up — work on the product",
            'sub': "No urgent moves on the pipeline right now",
            'href': "/admin/marketing/lead/",
        })

    return moves[:3]


def _stuck_leads() -> list[dict]:
    """Detect pipeline leaks: leads sitting in a stage longer than expected.

    Lead has no status-history table, so we proxy "time in stage" with the
    most-recent operator-touch we can prove from the row's timestamps:
    max(last_followup_at, contacted_at, created_at). If that's older than
    the per-stage threshold, the lead is going cold.
    """
    now = timezone.now()
    rules = [
        ('new',         'New',         1),  # > 1 day uncontacted
        ('sent',        'Sent',        7),  # > 7d ghosting
        ('replied',     'Replied',     5),  # > 5d cold after they replied
        ('demo_booked', 'Demo booked', 7),  # > 7d post-demo without close
    ]
    out = []
    for status, label, threshold_days in rules:
        cutoff = now - timedelta(days=threshold_days)
        cnt = 0
        qs = Lead.objects.filter(status=status).only(
            'id', 'created_at', 'contacted_at', 'last_followup_at'
        )
        for lead in qs.iterator():
            last_touch = max(
                t for t in (lead.created_at, lead.contacted_at, lead.last_followup_at)
                if t is not None
            )
            if last_touch < cutoff:
                cnt += 1
        if cnt:
            out.append({
                'status': status,
                'label': label,
                'count': cnt,
                'days': threshold_days,
                'href': f"/admin/marketing/lead/?status__exact={status}",
            })
    return out


def _today_timeline(limit: int = 30) -> list[dict]:
    """Chronological feed of today's lead events.

    Pulls from the Lead row's natural timestamps — `contacted_at`, `engaged_at`,
    `last_visited_at`, `last_followup_at`, `created_at` — and merges them by
    time, newest first. No status-history table needed.
    """
    today = date.today()
    events = []

    fields = [
        ('created_at',       '🌱', 'New lead added',        '{name}'),
        ('contacted_at',     '📲', 'You contacted',         '{name}'),
        ('engaged_at',       '✨', 'First-time page open',  '{name}'),
        ('last_visited_at',  '👀', 'Returned to their page', '{name}'),
        ('last_followup_at', '📨', 'Follow-up sent',        '{name}'),
    ]
    for field, emoji, action, _detail in fields:
        kwargs = {f'{field}__date': today, f'{field}__isnull': False}
        for lead in Lead.objects.filter(**kwargs).only('id', 'name', field).order_by(f'-{field}')[:limit]:
            ts = getattr(lead, field)
            # Skip noisy duplicate: engaged_at == last_visited_at on first open.
            if field == 'last_visited_at' and lead.engaged_at and abs(
                (ts - lead.engaged_at).total_seconds()
            ) < 5:
                continue
            events.append({
                'ts': ts,
                'emoji': emoji,
                'action': action,
                'name': lead.name,
                'lead_id': lead.id,
                'time_str': timezone.localtime(ts).strftime('%H:%M'),
            })

    events.sort(key=lambda e: e['ts'], reverse=True)
    return events[:limit]


def _goals_and_streak(cfg) -> dict:
    """Weekly outreach + monthly demo/pilot goals + contacting streak.

    Targets come from the editable DashboardConfig singleton. Streak = number
    of consecutive days (counting back from today, or yesterday if today is
    empty) with at least one `contacted_at` event.
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    month_start = today.replace(day=1)

    targets = {
        'outreach_week': cfg.goal_outreach_per_week,
        'demos_week':    cfg.goal_demos_per_week,
        'pilots_month':  cfg.goal_pilots_per_month,
    }

    outreach_week = Lead.objects.filter(contacted_at__date__gte=week_start).count()
    # No `updated_at` on Lead; approximate "moved to this stage this week"
    # with `contacted_at` — close enough for a goal counter.
    demos_week = Lead.objects.filter(
        status='demo_booked', contacted_at__date__gte=week_start
    ).count()
    pilots_month = Lead.objects.filter(
        status='pilot', contacted_at__date__gte=month_start
    ).count()

    # Contacting streak — walk back day by day until we hit a zero day.
    # Today counts as "live" if any contact happened; otherwise we forgive
    # today (people often check the dashboard before doing the day's work)
    # and start the count from yesterday.
    contacted_dates = set(
        d for d in Lead.objects.filter(
            contacted_at__date__gte=today - timedelta(days=60)
        ).values_list('contacted_at__date', flat=True) if d
    )
    streak = 0
    cursor = today if today in contacted_dates else today - timedelta(days=1)
    while cursor in contacted_dates:
        streak += 1
        cursor -= timedelta(days=1)

    def _pct(actual: int, target: int) -> int:
        return min(100, round((actual / target) * 100)) if target else 0

    return {
        'goals': [
            {
                'key': 'outreach_week', 'label': 'Outreach this week',
                'actual': outreach_week, 'target': targets['outreach_week'],
                'pct': _pct(outreach_week, targets['outreach_week']),
                'tone': 'cyan',
            },
            {
                'key': 'demos_week', 'label': 'Demos this week',
                'actual': demos_week, 'target': targets['demos_week'],
                'pct': _pct(demos_week, targets['demos_week']),
                'tone': 'amber',
            },
            {
                'key': 'pilots_month', 'label': 'Pilots this month',
                'actual': pilots_month, 'target': targets['pilots_month'],
                'pct': _pct(pilots_month, targets['pilots_month']),
                'tone': 'green',
            },
        ],
        'streak': streak,
        'streak_active_today': today in contacted_dates,
    }


def dashboard_metrics() -> dict:
    """Single function returning everything the war-room template needs."""
    from .models import DashboardConfig
    cfg = DashboardConfig.load()

    funnel = _funnel_counts()
    rates = _stage_rates(funnel, cfg)
    pv = _pipeline_value(funnel, cfg, rates)

    today = date.today()
    week_ago = today - timedelta(days=7)
    yesterday = today - timedelta(days=1)
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    new_today = Lead.objects.filter(created_at__date=today).count()
    new_yesterday = Lead.objects.filter(created_at__date=yesterday).count()
    delta_today = new_today - new_yesterday

    contacted_today = Lead.objects.filter(contacted_at__date=today).count()
    engaged_now = Lead.objects.filter(last_visited_at__gte=hour_ago).count()
    week_leads = Lead.objects.filter(created_at__date__gte=week_ago).count()

    sent_total = sum(funnel.get(s, 0) for s in ('sent', 'replied', 'demo_booked', 'pilot'))
    replied_total = sum(funnel.get(s, 0) for s in ('replied', 'demo_booked', 'pilot'))
    reply_rate = round((replied_total / sent_total) * 100) if sent_total else 0

    # Roll up calibration mode for the UI label: "observed" only if EVERY
    # transition is observed; otherwise "mixed" or "benchmark".
    modes = {r['mode'] for r in rates.values()}
    if modes == {'observed'}:
        calibration_mode = 'observed'
    elif modes == {'benchmark'}:
        calibration_mode = 'benchmark'
    else:
        calibration_mode = 'mixed'

    return {
        'pipeline_value': pv,
        'pipeline_value_inr_short': _short_inr(pv),
        'calibration': {
            'mode': calibration_mode,
            'arpu_inr': cfg.arpu_inr,
            'min_sample_size': cfg.min_sample_size,
            'rates': [
                {
                    'transition': r['transition'],
                    'pct': round(r['value'] * 100, 1),
                    'mode': r['mode'],
                    'sample': r['sample'],
                    'needs': r.get('needs', 0),
                }
                for r in rates.values()
            ],
        },
        'funnel': [
            {'key': 'new',         'label': 'New',         'count': funnel['new']},
            {'key': 'sent',        'label': 'Sent',        'count': funnel['sent']},
            {'key': 'replied',     'label': 'Replied',     'count': funnel['replied']},
            {'key': 'demo_booked', 'label': 'Demo',        'count': funnel['demo_booked']},
            {'key': 'pilot',       'label': 'Pilot',       'count': funnel['pilot']},
        ],
        'sparkline_14d': _last_n_days_lead_counts(14),
        'next_moves': _next_moves(),
        'stuck': _stuck_leads(),
        'timeline': _today_timeline(),
        'goals_streak': _goals_and_streak(cfg),
        'kpis': {
            'new_today': new_today,
            'delta_today': delta_today,
            'contacted_today': contacted_today,
            'engaged_now': engaged_now,
            'week_leads': week_leads,
            'reply_rate': reply_rate,
        },
    }


def _short_inr(v: int) -> str:
    """Format ₹ for the hero — Indian-style lakhs/crores."""
    if v >= 10_000_000:
        return f"₹{v / 10_000_000:.1f} Cr"
    if v >= 100_000:
        return f"₹{v / 100_000:.1f} L"
    if v >= 1_000:
        return f"₹{v / 1_000:.0f}K"
    return f"₹{v}"


# ─── AI briefing ─────────────────────────────────────────────────────────

@require_GET
def ai_briefing_view(request):
    """Groq-generated 1-paragraph briefing of the day's pipeline.

    Cached for 30 minutes per user — the founder reloads the dashboard a lot
    and the briefing doesn't need to be fresher than that.
    """
    cache_key = f"docping:dashboard:briefing:{request.user.pk}"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse({'ok': True, 'briefing': cached, 'cached': True})

    api_key = getattr(settings, 'GROQ_API_KEY', '')
    if not api_key:
        return JsonResponse({
            'ok': False,
            'error': 'GROQ_API_KEY not configured.',
        }, status=400)

    metrics = dashboard_metrics()
    funnel_str = ', '.join(f"{f['label']}: {f['count']}" for f in metrics['funnel'])
    kpis = metrics['kpis']

    prompt = f"""You are the AI co-pilot for Aniket, the solo founder of DocPing — a WhatsApp-based clinic appointment booking SaaS in India. He runs outbound sales by hand. Write him a single short, conversational briefing paragraph (60-90 words) for his dashboard.

Today's pipeline state:
- Funnel counts: {funnel_str}
- Pipeline value: {metrics['pipeline_value_inr_short']} potential MRR
- New leads today: {kpis['new_today']} (vs {kpis['new_today'] - kpis['delta_today']} yesterday)
- Contacted today: {kpis['contacted_today']}
- Engaged in last hour: {kpis['engaged_now']}
- Reply rate so far: {kpis['reply_rate']}%
- Last 14d new leads: {metrics['sparkline_14d']}

Rules:
- Sound like a sharp friend, not a corporate dashboard. Lower-case OK.
- Lead with the most actionable observation.
- Recommend ONE concrete move he should make today.
- No greetings, no sign-off, no markdown headers — just the paragraph.
- 60-90 words, hard cap.
- If everything is dead (zero replies, zero demos), be honest about it without being defeatist.
"""

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=260,
        )
        briefing = (r.choices[0].message.content or '').strip()
        cache.set(cache_key, briefing, 60 * 30)  # 30 min
        return JsonResponse({'ok': True, 'briefing': briefing, 'cached': False})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'Groq call failed: {e}'}, status=500)


# ─── Header signals (light, runs on every admin page) ───────────────────

@require_GET
def header_signals_view(request):
    """Lightweight numbers for the global header strip — runs on every admin
    page via JS poll so we keep it cheap (3 trivial counts, no per-row walks)."""
    now = timezone.now()
    today = now.date()
    hour_ago = now - timedelta(hours=1)
    hot_now = Lead.objects.filter(last_visited_at__gte=hour_ago).count()
    sent_today = Lead.objects.filter(contacted_at__date=today).count()
    return JsonResponse({
        'ok': True,
        'hot_now': hot_now,
        'sent_today': sent_today,
        'time_str': timezone.localtime().strftime('%I:%M %p').lstrip('0'),
        'iso': timezone.localtime().isoformat(),
    })


# ─── Notifications tray (bell icon) ──────────────────────────────────────

@require_GET
def notifications_view(request):
    """Aggregates anything that needs the operator's attention right now:
    leads currently on their page, leads going stale, demos in the next hour."""
    now = timezone.now()
    today = now.date()
    hour_ago = now - timedelta(hours=1)
    next_hour = now + timedelta(hours=1)

    items = []

    # 1) Live engaged
    for lead in Lead.objects.filter(last_visited_at__gte=hour_ago).order_by('-last_visited_at')[:5]:
        items.append({
            'tone': 'hot',
            'emoji': '🔥',
            'title': f"{lead.name} is on their page",
            'sub': f"visit #{lead.visit_count} · {timezone.localtime(lead.last_visited_at).strftime('%I:%M %p').lstrip('0')}",
            'href': f"/admin/marketing/lead/?_drawer={lead.pk}",
            'ts': lead.last_visited_at.isoformat(),
        })

    # 2) Stuck leaks
    for s in _stuck_leads():
        items.append({
            'tone': 'amber',
            'emoji': '⚠',
            'title': f"{s['count']} stuck in {s['label']} for >{s['days']}d",
            'sub': "click to clean up",
            'href': s['href'],
            'ts': now.isoformat(),
        })

    # 3) Demos in the next hour (clinic patient appointments — useful for
    # the operations side; covers "you have a call coming up").
    try:
        from apps.clinic.models import Appointment
        upcoming = Appointment.objects.filter(
            slot__date=today,
            slot__time__gte=now.time(),
            slot__time__lt=next_hour.time(),
            status='booked',
        ).select_related('patient', 'doctor')[:5]
        for ap in upcoming:
            items.append({
                'tone': 'cyan',
                'emoji': '⏰',
                'title': f"{ap.patient.name} · Dr. {ap.doctor.name}",
                'sub': f"{ap.slot.time.strftime('%I:%M %p').lstrip('0')} — coming up",
                'href': f"/admin/clinic/appointment/{ap.pk}/change/",
                'ts': now.isoformat(),
            })
    except Exception:
        pass

    return JsonResponse({'ok': True, 'count': len(items), 'items': items})


# ─── ⌘K command palette search ───────────────────────────────────────────

# Static command catalog. Each entry: (keywords, emoji, title, desc, href).
# The href can be relative to /admin or absolute. Keywords are lowercase.
_COMMANDS = [
    ('home dashboard war room',          '🏠',  'Open dashboard',           'Back to the war-room home',
     '/admin/'),
    ('leads list',                       '👥',  'Open leads list',           'All leads, filterable',
     '/admin/marketing/lead/'),
    ('hot followup needs follow-up due', '🔥',  'Leads needing follow-up',   'Filter to anyone due a ping',
     '/admin/marketing/lead/?needs_followup=1'),
    ('engaged hot active visiting',      '👀',  'Currently engaged leads',   'Leads who opened their page recently',
     '/admin/marketing/lead/?engaged=1'),
    ('demo booked demos',                '📅',  'Demos booked',              'Filter to demo-booked leads',
     '/admin/marketing/lead/?status__exact=demo_booked'),
    ('pilot pilots active',              '🎉',  'Active pilots',             'Filter to pilot-stage leads',
     '/admin/marketing/lead/?status__exact=pilot'),
    ('appointments today schedule',      '🗓',  'Appointments',              "Today's clinic appointments",
     '/admin/clinic/appointment/'),
    ('available slots calendar',         '⏱',  'Available slots',           'Demo doctor calendar',
     '/admin/clinic/availableslot/'),
    ('patients',                         '🧑',  'Patients',                   'All registered patients',
     '/admin/clinic/patient/'),
    ('doctors',                          '🩺',  'Doctors',                   'All registered doctors',
     '/admin/clinic/doctor/'),
    ('run lead-gen leadgen places google fetch', '🌱',  'Run lead-gen now',
     'Pull fresh clinics from Google Places',
     '/admin/marketing/lead/run-leadgen-now/'),
    ('config dashboard goals targets arpu',      '⚙',  'Dashboard config',
     'Tune ARPU, goal targets, conversion thresholds',
     '/admin/marketing/dashboardconfig/'),
    ('demo videos library',              '🎥',  'Demo videos',               'Marketing demo videos library',
     '/admin/marketing/demovideo/'),
    ('logout sign out',                  '🚪',  'Log out',                   'End the admin session',
     '/admin/logout/'),
]


@require_GET
def command_search_view(request):
    """Powers the ⌘K palette: type-to-search across leads + canned commands."""
    from django.db.models import Q
    raw = (request.GET.get('q', '') or '').strip()
    q = raw.lower()

    leads_out = []
    cmds_out = []

    if q:
        # Lead match — try phone digits first, then name/address.
        digits = ''.join(c for c in raw if c.isdigit())
        qs = Lead.objects.all()
        if digits and len(digits) >= 4:
            qs = qs.filter(phone__icontains=digits)
        else:
            qs = qs.filter(Q(name__icontains=raw) | Q(address__icontains=raw))
        for lead in qs.order_by('-score', '-created_at')[:6]:
            leads_out.append({
                'id': lead.pk,
                'name': lead.name,
                'phone': lead.phone,
                'status': lead.get_status_display(),
                'score': lead.score,
                'href': f"/admin/marketing/lead/?_drawer={lead.pk}",
            })

        # Command match — every term in q must appear in either keywords
        # or title (substring), so multi-word queries narrow down.
        terms = q.split()
        for keywords, emoji, title, desc, href in _COMMANDS:
            haystack = (keywords + ' ' + title.lower()).strip()
            if all(t in haystack for t in terms):
                cmds_out.append({
                    'emoji': emoji, 'title': title, 'desc': desc, 'href': href,
                })
    else:
        # Empty query — show top 6 commands as suggestions.
        for keywords, emoji, title, desc, href in _COMMANDS[:6]:
            cmds_out.append({
                'emoji': emoji, 'title': title, 'desc': desc, 'href': href,
            })

    return JsonResponse({'ok': True, 'leads': leads_out, 'commands': cmds_out})


# ─── Live engagement pulse ───────────────────────────────────────────────

@require_GET
def engagement_pulse_view(request):
    """Return leads that visited their personalised page in the last N seconds.

    The dashboard polls this every 30s and shows a toast for any newly seen
    lead. We rely on the client to track which IDs it has already shown.
    """
    try:
        seconds = int(request.GET.get('since', 90))
    except ValueError:
        seconds = 90
    seconds = max(15, min(seconds, 300))

    cutoff = timezone.now() - timedelta(seconds=seconds)
    qs = (
        Lead.objects
        .filter(last_visited_at__gte=cutoff)
        .order_by('-last_visited_at')
        .values('id', 'name', 'phone', 'visit_count', 'last_visited_at', 'engaged_at')[:8]
    )
    items = []
    for r in qs:
        items.append({
            'id': r['id'],
            'name': r['name'],
            'phone': r['phone'],
            'visit_count': r['visit_count'],
            'last_seen_iso': r['last_visited_at'].isoformat() if r['last_visited_at'] else None,
            'first_open_iso': r['engaged_at'].isoformat() if r['engaged_at'] else None,
            'drawer_url': f"/admin/marketing/lead/?_drawer={r['id']}",
        })
    return JsonResponse({'ok': True, 'items': items, 'now_iso': timezone.now().isoformat()})
