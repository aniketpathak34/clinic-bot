from datetime import date, timedelta

from django.contrib import admin, messages
from django.db.models import Count
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse, NoReverseMatch
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from .models import DemoVideo, Lead


# ─── Visual helpers ───────────────────────────────────────────────

STATUS_STYLE = {
    'new':            ('#94a3b8', '🆕', 'New'),
    'sent':           ('#3b82f6', '✉️', 'Sent'),
    'replied':        ('#8b5cf6', '💬', 'Replied'),
    'demo_booked':    ('#f59e0b', '📅', 'Demo'),
    'pilot':          ('#22c55e', '🎉', 'Pilot'),
    'not_interested': ('#ef4444', '🚫', 'Lost'),
    'invalid':        ('#6b7280', '⚠️', 'Invalid'),
}


def _score_tier(score: int):
    """Return (color, label, glyph) for a 'gold/silver/bronze' badge."""
    if score >= 21:
        return ('#fbbf24', 'Gold',   '🥇')
    if score >= 17:
        return ('#94a3b8', 'Silver', '🥈')
    if score >= 13:
        return ('#b45309', 'Bronze', '🥉')
    return ('#475569', 'Lead', '·')


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        'score_badge', 'name_card', 'phone_link', 'rating_display', 'reviews',
        'status', 'action_pill', 'whatsapp_button', 'age_display',
    )
    list_display_links = ('name_card',)
    list_editable = ('status',)
    list_filter = ('status', 'rating')
    search_fields = ('name', 'phone', 'address')
    readonly_fields = ('place_id', 'last_seen_at', 'created_at')
    # Newest leads on top — most recently scraped or added to the DB.
    ordering = ('-created_at',)
    actions = ['mark_as_sent', 'mark_as_replied', 'mark_as_not_interested']
    change_list_template = 'admin/marketing/lead/change_list.html'
    list_per_page = 20

    # ─── Smarter search: strip non-digits when the term looks like a phone ───

    def get_search_results(self, request, queryset, search_term):
        """Make phone search forgiving — strip spaces, dashes, plus signs.

        If the user types '+91 70303 44210' or '70303-44210' or '7030344210',
        we extract just the digits and match against the stored phone field
        (which is digits-only with country code, e.g. '917030344210').
        Falls back to the original term for non-numeric searches (name/address).
        """
        import re
        if search_term and re.search(r'\d{5,}', search_term):
            digits = re.sub(r'\D', '', search_term)
            if digits:
                # Run both: digits-only AND original term, then union the results.
                qs_digits, _ = super().get_search_results(request, queryset, digits)
                qs_orig, _ = super().get_search_results(request, queryset, search_term)
                return (qs_digits | qs_orig).distinct(), True
        return super().get_search_results(request, queryset, search_term)

    # ─── Custom admin URL: "Run lead-gen now" ─────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'run-leadgen-now/',
                self.admin_site.admin_view(self.run_leadgen_view),
                name='marketing_lead_run_leadgen',
            ),
            path(
                '<int:pk>/drawer/',
                self.admin_site.admin_view(self.drawer_view),
                name='marketing_lead_drawer',
            ),
            path(
                '<int:pk>/quick-update/',
                self.admin_site.admin_view(self.drawer_save_view),
                name='marketing_lead_quick_update',
            ),
            path(
                '<int:pk>/ai-followup/',
                self.admin_site.admin_view(self.ai_followup_view),
                name='marketing_lead_ai_followup',
            ),
            path(
                '<int:pk>/followup-taken/',
                self.admin_site.admin_view(self.followup_taken_view),
                name='marketing_lead_followup_taken',
            ),
        ]
        return custom + urls

    @staticmethod
    @require_POST
    def followup_taken_view(request, pk):
        """Record that the operator clicked a follow-up template button.

        Called via fire-and-forget fetch() from the drawer — sets
        last_followup_at + last_followup_template on the lead so the
        action pill respects the cooldown period.
        """
        lead = get_object_or_404(Lead, pk=pk)
        template = request.POST.get('template', '')[:40]
        lead.last_followup_at = timezone.now()
        lead.last_followup_template = template
        lead.save(update_fields=['last_followup_at', 'last_followup_template'])
        return JsonResponse({
            'ok': True,
            'recorded_at': lead.last_followup_at.isoformat(),
            'template': lead.last_followup_template,
        })

    def drawer_view(self, request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        words = (lead.name or '').strip().split()
        initials = (''.join(w[0] for w in words[:2]) or '·').upper()[:2]
        palette = ['#22d3ee', '#a855f7', '#f59e0b', '#10b981',
                   '#ef4444', '#3b82f6', '#ec4899', '#8b5cf6']
        avatar_color = palette[(sum(ord(c) for c in (lead.name or ''))) % len(palette)]
        tier_color, tier_label, _ = _score_tier(lead.score or 0)
        status_color = STATUS_STYLE.get(lead.status, ('#6b7280', '', ''))[0]
        types_list = [t.strip().replace('_', ' ').title()
                      for t in (lead.types or '').split(',') if t.strip()][:8]
        return render(request, 'admin/marketing/lead/drawer.html', {
            'lead': lead,
            'initials': initials,
            'avatar_color': avatar_color,
            'tier_color': tier_color,
            'tier_label': tier_label,
            'status_color': status_color,
            'status_choices': Lead.STATUS_CHOICES,
            'types_list': types_list,
            'landing_url': lead.landing_url,
            'followup_action': lead.followup_status(),
        })

    @staticmethod
    @require_POST
    def ai_followup_view(request, pk):
        """Use Groq (Llama 3.3 70B) to draft a personalised WhatsApp follow-up.

        Cheap (free tier covers >>100/day) and fast (<1s). Caches the most
        recent draft on the Lead so the operator can review without re-spending.
        """
        from django.conf import settings
        lead = get_object_or_404(Lead, pk=pk)
        api_key = getattr(settings, 'GROQ_API_KEY', '')
        if not api_key:
            return JsonResponse({
                'ok': False,
                'error': 'GROQ_API_KEY not configured. Set it in Render env vars.',
            }, status=400)

        # Pick a fresh angle so successive drafts feel different.
        import random
        angles = [
            ('roi-math',     'Hyper-specific ROI math — pull a number from their reviews count and tie it to recoverable revenue.'),
            ('social-proof', 'Mention that 2 other Pune clinics signed up this week (no names). Build urgency without sounding salesy.'),
            ('curiosity',    'Open with a question they will want answered (about a problem most clinics in their specialty face).'),
            ('scarcity',     'Mention only 3 free pilot slots left (real — that is the offer). Soft urgency.'),
            ('value-add',    'Give one tip they can use today, with no ask. Pure value. Then a soft CTA.'),
        ]
        chosen_angle, angle_brief = random.choice(angles)
        days_since = (timezone.now() - lead.created_at).days if lead.created_at else 0

        prompt = f"""You are an Indian SaaS founder named Aniket writing a WhatsApp follow-up to a clinic in Pune that hasn't replied yet.

Clinic: {lead.name}
Specialty: {lead.specialty}
Reviews: {lead.reviews} ({lead.rating}★)
Days since first outreach: {days_since}
Last status: {lead.get_status_display()}
Engagement: {'opened the page' if lead.engaged_at else 'has not opened the personalised page yet'}

Angle for THIS follow-up: {chosen_angle} — {angle_brief}

Write a short WhatsApp message (60-90 words MAX) that:
1. Sounds like a human Indian founder, not corporate copy
2. Uses Hinglish lightly (1-2 words max — like "ekdum" or "thoda") — do not overdo
3. Opens with a hook (NOT "just following up" or "circling back")
4. Mentions something specific to their clinic ({lead.name} or their {lead.reviews} reviews)
5. Has ONE clear soft CTA at the end
6. Signs off as "— Aniket" (no last name needed)

Output ONLY the message text, no preamble, no quotes, no explanation."""

        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.85,
                max_tokens=300,
            )
            draft = (r.choices[0].message.content or '').strip()
            lead.ai_followup_draft = draft
            lead.save(update_fields=['ai_followup_draft'])
            return JsonResponse({'ok': True, 'draft': draft, 'angle': chosen_angle})
        except Exception as e:
            return JsonResponse({'ok': False, 'error': f'Groq call failed: {e}'}, status=500)

    @staticmethod
    @require_POST
    def drawer_save_view(request, pk):
        lead = get_object_or_404(Lead, pk=pk)
        update_fields = []
        if 'notes' in request.POST:
            lead.notes = request.POST.get('notes', '')[:2000]
            update_fields.append('notes')
        if 'status' in request.POST:
            valid = {s for s, _ in Lead.STATUS_CHOICES}
            new_status = request.POST.get('status')
            if new_status in valid:
                lead.status = new_status
                update_fields.append('status')
                if new_status == 'sent' and not lead.contacted_at:
                    lead.contacted_at = timezone.now()
                    update_fields.append('contacted_at')
        if 'mark_contacted' in request.POST:
            lead.contacted_at = timezone.now()
            update_fields.append('contacted_at')
        if update_fields:
            lead.save(update_fields=update_fields)
        return JsonResponse({
            'ok': True,
            'status': lead.status,
            'status_display': lead.get_status_display(),
            'contacted_at': lead.contacted_at.isoformat() if lead.contacted_at else None,
        })

    def run_leadgen_view(self, request):
        """Synchronous trigger — runs Google Places scraper inline.
        No Celery worker needed; takes ~5-10 seconds."""
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        try:
            call_command('seed_leads', stdout=out, stderr=out)
            self.message_user(
                request,
                f"✓ Lead-gen complete. {out.getvalue().splitlines()[-1] if out.getvalue() else ''}",
                level=messages.SUCCESS,
            )
        except Exception as e:
            self.message_user(request, f"❌ Lead-gen failed: {e}", level=messages.ERROR)
        return HttpResponseRedirect(reverse('admin:marketing_lead_changelist'))

    # ─── Stat strip shown above the changelist table ─────────────

    def get_queryset(self, request):
        """Hook the 'needs_followup' URL param (stashed on the request by
        changelist_view) to filter to leads needing action right now."""
        qs = super().get_queryset(request)
        if getattr(request, '_filter_needs_followup', False):
            ids = [l.pk for l in qs if l.followup_status() is not None]
            qs = qs.filter(pk__in=ids)
        return qs

    def changelist_view(self, request, extra_context=None):
        # Pop our custom param BEFORE Django admin's ChangeList validates
        # query params (unknown params trigger a redirect with ?e=1 error).
        request._filter_needs_followup = request.GET.get('needs_followup') == '1'
        if request._filter_needs_followup:
            get = request.GET.copy()
            get.pop('needs_followup', None)
            request.GET = get

        today = date.today()
        week_ago = today - timedelta(days=7)
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        qs = Lead.objects.all()
        sent_total = qs.filter(status__in=['sent', 'replied', 'demo_booked', 'pilot']).count()
        replied = qs.filter(status__in=['replied', 'demo_booked', 'pilot']).count()
        pilots = qs.filter(status='pilot').count()
        # Per-status counts for the filter chips
        status_counts = {row['status']: row['c']
                         for row in qs.values('status').annotate(c=Count('id'))}
        engaged_total = qs.filter(engaged_at__isnull=False).count()
        engaged_24h = qs.filter(engaged_at__gte=day_ago).count()
        engaged_hot = qs.filter(last_visited_at__gte=hour_ago).count()

        # Count leads needing follow-up by urgency
        action_hot = sum(1 for l in qs if (a := l.followup_status()) and a['urgency'] == 'hot')
        action_medium = sum(1 for l in qs if (a := l.followup_status()) and a['urgency'] == 'medium')
        action_low = sum(1 for l in qs if (a := l.followup_status()) and a['urgency'] == 'low')
        action_total = action_hot + action_medium + action_low
        stats = {
            'total': qs.count(),
            'new_today': qs.filter(created_at__date=today).count(),
            'new_week': qs.filter(created_at__date__gte=week_ago).count(),
            'sent_total': sent_total,
            'replied': replied,
            'demos': qs.filter(status='demo_booked').count(),
            'pilots': pilots,
            'reply_rate': round((replied / sent_total) * 100) if sent_total else 0,
            'pilot_rate': round((pilots / sent_total) * 100) if sent_total else 0,
            'gold': qs.filter(score__gte=21).count(),
            'silver': qs.filter(score__gte=17, score__lt=21).count(),
            'fresh_new': qs.filter(status='new').count(),
            'by_status': status_counts,
            'engaged_total': engaged_total,
            'action_total': action_total,
            'action_hot': action_hot,
            'action_medium': action_medium,
            'action_low': action_low,
            'engaged_24h': engaged_24h,
            'engaged_hot': engaged_hot,
        }
        extra_context = extra_context or {}
        extra_context['lead_stats'] = stats
        # Pass the actual admin URL prefix so the drawer/quick-update/AI-followup
        # JS calls work whether admin lives at /admin/ or a custom env-set path.
        extra_context['admin_lead_url_prefix'] = reverse('admin:marketing_lead_changelist').rstrip('/')
        # Pass our custom filter state to the template (since we popped it from GET).
        extra_context['filter_needs_followup'] = getattr(request, '_filter_needs_followup', False)
        return super().changelist_view(request, extra_context=extra_context)

    fieldsets = (
        (None, {
            'fields': ('name', 'phone', 'rating', 'reviews', 'address',
                       'google_maps_url', 'types'),
        }),
        ('Pipeline', {
            'fields': ('score', 'status', 'notes', 'contacted_at'),
        }),
        ('Source', {
            'classes': ('collapse',),
            'fields': ('place_id', 'last_seen_at', 'created_at'),
        }),
    )

    # ─── Column renderers ────────────────────────────────────────

    def score_badge(self, obj):
        score = obj.score or 0
        color, label, _ = _score_tier(score)
        # 25 is roughly the practical ceiling for our scoring system
        pct = max(8, min(100, int(score / 25 * 100)))
        return format_html(
            '<div title="{} tier" style="display:flex;flex-direction:column;gap:4px;'
            'min-width:60px;font-family:JetBrains Mono,monospace;">'
            '<span style="font-size:13px;font-weight:700;color:{};letter-spacing:-.02em;">{}</span>'
            '<span style="display:block;height:3px;width:60px;background:rgba(255,255,255,.06);'
            'border-radius:2px;overflow:hidden;">'
            '<span style="display:block;height:100%;width:{}%;background:{};border-radius:2px;'
            'box-shadow:0 0 6px {}55;transition:width .4s ease;"></span></span>'
            '</div>',
            label, color, score, pct, color, color,
        )
    score_badge.short_description = 'Score'
    score_badge.admin_order_field = 'score'

    def name_card(self, obj):
        words = (obj.name or '').strip().split()
        initials = (''.join(w[0] for w in words[:2]) or '·').upper()[:2]
        palette = ['#22d3ee', '#a855f7', '#f59e0b', '#10b981',
                   '#ef4444', '#3b82f6', '#ec4899', '#8b5cf6']
        color = palette[(sum(ord(c) for c in (obj.name or '')) ) % len(palette)]
        return format_html(
            '<div style="display:flex;align-items:center;gap:10px;">'
            '<span style="display:inline-flex;align-items:center;justify-content:center;'
            'width:32px;height:32px;border-radius:8px;background:{}1f;color:{};'
            'font-weight:700;font-size:11px;letter-spacing:.02em;'
            'border:1px solid {}40;flex-shrink:0;font-family:Inter,sans-serif;">{}</span>'
            '<span style="font-weight:600;color:#f4f4f5;">{}</span>'
            '</div>',
            color, color, color, initials, obj.name,
        )
    name_card.short_description = 'Clinic'
    name_card.admin_order_field = 'name'

    def status_pill(self, obj):
        color, _, short = STATUS_STYLE.get(
            obj.status, ('#6b7280', '•', obj.get_status_display())
        )
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:6px;'
            'background:{}14;color:{};padding:3px 10px;border-radius:6px;'
            'font-weight:500;font-size:12px;font-family:Inter,sans-serif;">'
            '<span style="width:6px;height:6px;background:{};border-radius:50%;"></span>'
            '{}</span>',
            color, color, color, short,
        )
    status_pill.short_description = 'Status'
    status_pill.admin_order_field = 'status'

    def phone_link(self, obj):
        # Pretty +CC NNNNN-NNNNN format if Indian 12-digit, else as-is.
        raw = obj.phone or ''
        if len(raw) == 12 and raw.startswith('91'):
            pretty = f"+91 {raw[2:7]}-{raw[7:]}"
        else:
            pretty = f"+{raw}"
        return format_html(
            '<a href="tel:+{}" style="font-family:monospace;color:#0f766e;'
            'text-decoration:none;font-weight:600;">{}</a>',
            raw, pretty,
        )
    phone_link.short_description = 'Phone'

    def rating_display(self, obj):
        if obj.rating is None:
            return format_html('<span style="color:#cbd5e1;">—</span>')
        return format_html(
            '<span style="color:#f59e0b;font-size:13px;">★</span>'
            '<span style="color:#0f172a;margin-left:4px;font-weight:600;'
            'font-family:Inter,sans-serif;">{}</span>',
            f"{obj.rating:.1f}",
        )
    rating_display.short_description = 'Rating'
    rating_display.admin_order_field = 'rating'

    def whatsapp_button(self, obj):
        if obj.status in ('pilot', 'not_interested', 'invalid'):
            return format_html('<span style="color:#cbd5e1;">—</span>')
        return format_html(
            '<a href="{}" target="_blank" '
            'style="background:#fff;color:#16a34a;border:1px solid #bbf7d0;'
            'padding:5px 12px;border-radius:6px;text-decoration:none;font-weight:500;'
            'font-size:12px;font-family:Inter,sans-serif;">Send →</a>',
            obj.whatsapp_link,
        )
    whatsapp_button.short_description = 'Outreach'

    URGENCY_COLORS = {
        'hot':    '#ef4444',  # red
        'medium': '#f59e0b',  # amber
        'low':    '#3b82f6',  # blue
        'cold':   '#71717a',  # gray
    }

    def action_pill(self, obj):
        """Auto-detected follow-up urgency badge — what to do with this lead."""
        action = obj.followup_status()
        if not action:
            return format_html('<span style="color:#cbd5e1;">—</span>')
        color = self.URGENCY_COLORS.get(action['urgency'], '#71717a')
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:6px;'
            'background:{}14;color:{};padding:3px 10px;border-radius:6px;'
            'font-weight:500;font-size:12px;font-family:Inter,sans-serif;'
            'max-width:230px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            '" title="{}">{} {}</span>',
            color, color, action['label'], action['emoji'], action['label'],
        )
    action_pill.short_description = '🎯 Action'

    def age_display(self, obj):
        if not obj.created_at:
            return ''
        ts = obj.created_at.isoformat()
        delta = timezone.now() - obj.created_at
        if delta.total_seconds() < 60:
            label = 'just now'
        elif delta.total_seconds() < 3600:
            label = f'{int(delta.total_seconds() // 60)}m ago'
        elif delta.days == 0:
            label = f'{int(delta.total_seconds() // 3600)}h ago'
        elif delta.days == 1:
            label = 'yesterday'
        elif delta.days < 7:
            label = f'{delta.days}d ago'
        else:
            label = f'{delta.days // 7}w ago'
        return format_html(
            '<span class="lp-ago" data-ts="{}" '
            'style="color:#71717a;font-size:12px;'
            'font-family:JetBrains Mono,monospace;">{}</span>',
            ts, label,
        )
    age_display.short_description = 'Added'
    age_display.admin_order_field = 'created_at'

    # ─── Bulk actions ────────────────────────────────────────────

    def mark_as_sent(self, request, queryset):
        updated = queryset.update(status='sent', contacted_at=timezone.now())
        self.message_user(request, f"{updated} lead(s) marked as Sent.")
    mark_as_sent.short_description = "Mark selected as Sent"

    def mark_as_replied(self, request, queryset):
        updated = queryset.update(status='replied')
        self.message_user(request, f"{updated} lead(s) marked as Replied.")
    mark_as_replied.short_description = "Mark selected as Replied"

    def mark_as_not_interested(self, request, queryset):
        updated = queryset.update(status='not_interested')
        self.message_user(request, f"{updated} lead(s) marked as Not interested.")
    mark_as_not_interested.short_description = "Mark selected as Not interested"


@admin.register(DemoVideo)
class DemoVideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'role', 'order', 'is_active', 'preview', 'uploaded_at')
    list_editable = ('order', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = ('title', 'description')
    fieldsets = (
        (None, {
            'fields': ('title', 'role', 'description'),
        }),
        ('Video source', {
            'fields': ('embed_url', 'video_file', 'poster'),
            'description': (
                "Pick <b>one</b> of the two. YouTube/Vimeo URL is strongly "
                "preferred on Render free tier — uploaded files are wiped on every deploy."
            ),
        }),
        ('Display', {
            'fields': ('order', 'is_active'),
        }),
    )

    def preview(self, obj):
        if obj.is_youtube and obj.youtube_id:
            return format_html(
                '<a href="https://youtu.be/{}" target="_blank">▶ YouTube</a>', obj.youtube_id
            )
        if obj.video_file:
            return format_html('<a href="{}" target="_blank">▶ File</a>', obj.video_file.url)
        return '—'
    preview.short_description = 'Preview'
