"""Node functions for the doctor conversation flow — all responses interactive."""
import json
import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings

from apps.clinic.models import Clinic, Doctor, AvailableSlot, Appointment
from bot_locale.messages import get_msg
from apps.conversations.prompts.templates import AVAILABILITY_PARSE_PROMPT
from apps.conversations.response import BotResponse

logger = logging.getLogger(__name__)

def _time_key(t: time) -> str:
    return t.strftime('%H:%M')


def _time_display(t: time) -> str:
    return t.strftime('%I:%M %p').lstrip('0')


def _clinic_session_slots(clinic, ref_date: date, session: str) -> list:
    """Return (key, display) tuples for this clinic's slots on ref_date filtered by session.

    session: 'morning' | 'afternoon' | 'full_day'
    Uses the clinic's own operating_hours + slot granularity.
    """
    if not clinic:
        return []
    if session == 'morning':
        times = clinic.get_morning_slots(ref_date)
    elif session == 'afternoon':
        times = clinic.get_afternoon_slots(ref_date)
    else:
        times = clinic.get_slot_times(ref_date)
    return [(_time_key(t), _time_display(t)) for t in times]


def _all_time_display_map(clinic, ref_date: date) -> dict:
    """HH:MM -> "09:30 AM" for every time in the clinic's full-day slot set."""
    return {_time_key(t): _time_display(t) for t in clinic.get_slot_times(ref_date)}


# ─── Interactive Response Builders ───────────────────────────────

def _date_mode_buttons():
    """Preset shortcuts so the doctor doesn't have to tap 7 dates one-by-one."""
    return BotResponse.as_buttons(
        "📅 *Set your availability — choose a preset:*\n\n"
        "Pick a shortcut or set specific dates.",
        [
            {"id": "mode_next7", "title": "📅 Next 7 days"},
            {"id": "mode_weekdays", "title": "💼 Weekdays only"},
            {"id": "mode_custom_dates", "title": "🎯 Pick dates"},
        ]
    )


def _time_mode_buttons(session: str, date_count: int):
    """Preset shortcuts for times — apply ALL slots in the session or cherry-pick."""
    session_label = {
        'morning': 'morning',
        'afternoon': 'afternoon',
        'full_day': 'full day',
    }.get(session, 'session')
    return BotResponse.as_buttons(
        f"🕐 *{date_count} date(s) picked.*\n\n"
        f"Want every {session_label} slot, or pick specific times?",
        [
            {"id": "times_all", "title": "✅ All slots"},
            {"id": "times_custom", "title": "🎯 Pick times"},
        ]
    )


def _doctor_menu_list(doctor_name=None):
    body = f"Welcome, Dr. {doctor_name}! 👋\nWhat would you like to do?" if doctor_name else "Doctor Menu:"
    return BotResponse.as_list(
        body, "Choose Option",
        [
            {"id": "1", "title": "Set Availability", "description": "Add your available slots"},
            {"id": "2", "title": "Today's Bookings", "description": "View today's appointments"},
            {"id": "3", "title": "Upcoming Bookings", "description": "View all future appointments"},
        ]
    )


def _with_doctor_menu(prefix_text):
    menu = _doctor_menu_list()
    menu.text = f"{prefix_text}\n\n{menu.text}"
    return menu


def _next_7_days_list(selected_dates: list = None, clinic=None):
    """Interactive list of next 7 days — only shows days the clinic is open.

    Days when the clinic is closed (per operating_hours) are omitted entirely
    so a doctor cannot set availability when the clinic has no shifts.
    """
    selected_dates = selected_dates or []
    selected_set = set(selected_dates)

    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    today = date.today()
    rows = []
    friendly = {}
    for i in range(7):
        d = today + timedelta(days=i)
        if clinic and not clinic.is_open(d):
            continue
        day = day_names[d.weekday()]
        label = "Today" if i == 0 else ("Tomorrow" if i == 1 else f"{day}, {d.strftime('%d %b')}")
        friendly[d.isoformat()] = label.replace(', ', ' ')
        marker = "☑️ " if d.isoformat() in selected_set else "☐ "
        rows.append({
            "id": d.isoformat(),
            "title": (marker + label)[:24],
            "description": d.strftime('%d %B %Y'),
        })
        if len(rows) == 9:   # leave room for Done row within 10-row WhatsApp cap
            break

    count = len(selected_set)
    rows.append({
        "id": "done",
        "title": f"✅ Done ({count})" if count else "⏭️ Skip",
        "description": f"Save {count} date(s) and continue" if count else "Pick at least one date first",
    })

    if count:
        summary = ", ".join(friendly.get(d, d) for d in selected_dates)
        body = (
            f"📅 *{count} date{'s' if count != 1 else ''} picked:* {summary}\n\n"
            f"👉 Tap more dates to add, tap again to remove, or tap *✅ Done ({count})* to continue."
        )
    else:
        body = (
            "📅 *Pick the dates you are available.*\n\n"
            "• Tap a date — you'll see ☑️ next to it.\n"
            "• You can add as many as you want.\n"
            "• Tap *✅ Done* when finished.\n\n"
            "_(Days when the clinic is closed are hidden.)_"
        )

    return BotResponse.as_list(body, "Choose Dates", rows)


def _morning_afternoon_buttons():
    """Buttons to choose morning or afternoon session (single-select)."""
    return BotResponse.as_buttons(
        "Which session do you want to set for the selected date(s)?",
        [
            {"id": "morning", "title": "🌅 Morning"},
            {"id": "afternoon", "title": "🌇 Afternoon"},
            {"id": "full_day", "title": "📋 Full Day"},
        ]
    )


def _time_slots_list(clinic, ref_date: date, session: str, selected_times: list = None):
    """Interactive slot list derived from this clinic's operating hours.

    ref_date is used to pick the right weekday's shifts. If the doctor has
    selected several dates, we use the first one as the template (the UI
    applies the same times across all selected dates).
    """
    selected_times = selected_times or []
    selected_set = set(selected_times)

    slots = _clinic_session_slots(clinic, ref_date, session)

    session_label = {
        'morning': "🌅 *Morning slots*",
        'afternoon': "🌇 *Afternoon/evening slots*",
        'full_day': "📋 *All slots*",
    }.get(session, "📋 *Slots*")

    # Reserve 1 row for Done within WhatsApp's 10-row list cap
    slots = slots[:9]

    rows = []
    for k, v in slots:
        marker = "☑️ " if k in selected_set else "☐ "
        rows.append({"id": k, "title": (marker + v)[:24]})

    count = len(selected_set)
    rows.append({
        "id": "done",
        "title": f"✅ Done ({count})" if count else "⏭️ Cancel",
        "description": f"Save {count} time(s)" if count else "Pick at least one slot first",
    })

    display_map = _all_time_display_map(clinic, ref_date)
    if count:
        summary = ", ".join(display_map.get(k, k) for k in selected_times if k in display_map)
        body = (
            f"{session_label} — *{count} time{'s' if count != 1 else ''} picked:* {summary}\n\n"
            f"👉 Tap more slots to add, tap again to remove, or tap *✅ Done ({count})* to continue."
        )
    else:
        body = (
            f"{session_label}\n\n"
            "• Tap a time — you'll see ☑️ next to it.\n"
            "• Add as many slots as you want.\n"
            "• Tap *✅ Done* when finished."
        )

    return BotResponse.as_list(body, "Choose Times", rows)


# ─── Flow Handlers ───────────────────────────────────────────────

def _first_selected_date(context: dict) -> date:
    """Reference date for slot generation — use the first picked date or today."""
    dates = context.get('selected_dates', [])
    if dates:
        try:
            return datetime.strptime(dates[0], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pass
    return date.today()


def _parse_incoming_date(text: str):
    """Return a date from an ISO string, 'today'/'tomorrow', or a title like
    'Mon, 23 Apr'. Falls through common strptime formats. Returns None on fail.
    Leading emoji checkmarks from a toggled row are stripped.
    """
    t = text.strip()
    for marker in ('☑️ ', '☐ ', '✅ '):
        if t.startswith(marker):
            t = t[len(marker):].strip()
            break
    # ISO — list row id format
    try:
        return datetime.strptime(t, '%Y-%m-%d').date()
    except ValueError:
        pass
    low = t.lower()
    today = date.today()
    if low == 'today':
        return today
    if low == 'tomorrow':
        return today + timedelta(days=1)
    # Title format "Mon, 23 Mar" or "23 March 2026" etc.
    clean = t
    if ', ' in clean:
        clean = clean.split(', ', 1)[1]
    for fmt in ['%d %b', '%d %B', '%d %b %Y', '%d %B %Y', '%d-%b-%Y']:
        try:
            parsed = datetime.strptime(clean, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
            return parsed.date()
        except ValueError:
            continue
    return None


def _save_selected_availability(state):
    """Create AvailableSlot rows for every (selected_date × selected_time).

    Slots outside the clinic's operating hours for that specific date are
    skipped silently (reported in the summary), so picking a Saturday + a
    6 PM slot when the clinic closes Saturdays at 1 PM just drops that one.
    """
    context = state.context or {}
    doctor = Doctor.objects.select_related('clinic').get(whatsapp_number=state.whatsapp_number)
    clinic = doctor.clinic

    selected_dates = [
        datetime.strptime(d, '%Y-%m-%d').date()
        for d in context.get('selected_dates', [])
    ]
    selected_times = [
        datetime.strptime(t, '%H:%M').time()
        for t in context.get('selected_times', [])
    ]

    created = 0
    existed = 0
    out_of_hours = 0
    for d in selected_dates:
        valid_for_day = set(clinic.get_slot_times(d)) if clinic else None
        for t in selected_times:
            if valid_for_day is not None and t not in valid_for_day:
                out_of_hours += 1
                continue
            _, was_created = AvailableSlot.objects.get_or_create(
                doctor=doctor, date=d, time=t,
                defaults={'is_booked': False},
            )
            if was_created:
                created += 1
            else:
                existed += 1

    # Reset state
    state.current_flow = 'doctor_menu'
    state.step = ''
    state.context = {}
    state.save()

    date_labels = ", ".join(d.strftime('%d %b') for d in selected_dates)
    time_labels = ", ".join(t.strftime('%I:%M %p') for t in selected_times)
    notes = []
    if existed:
        notes.append(f"{existed} already existed")
    if out_of_hours:
        notes.append(f"{out_of_hours} skipped (outside clinic hours)")
    suffix = f"\n_({'; '.join(notes)})_" if notes else ""
    return _with_doctor_menu(
        f"✅ *Availability saved*\n\n"
        f"📅 Dates: {date_labels}\n"
        f"🕐 Times: {time_labels}\n\n"
        f"Total new slots: *{created}*{suffix}"
    )


def handle_doctor_menu(state, text):
    choice = text.strip().lower()
    menu_map = {
        '1': '1', 'set availability': '1', 'availability': '1', 'set': '1',
        '2': '2', "today's bookings": '2', 'today': '2', 'today bookings': '2',
        '3': '3', 'upcoming bookings': '3', 'upcoming': '3', 'all bookings': '3',
    }
    choice = menu_map.get(choice, choice)

    if choice == '1':
        state.current_flow = 'set_availability'
        state.step = 'choose_date_mode'
        state.context = {}
        state.save()
        return _date_mode_buttons(), state

    elif choice == '2':
        return view_today_bookings(state)

    elif choice == '3':
        return view_upcoming_bookings(state)

    else:
        return _doctor_menu_list(), state


def handle_set_availability(state, text):
    """Interactive availability setting flow — presets + multi-select fallback."""
    context = state.context or {}
    text_raw = text.strip()
    text_lower = text_raw.lower()

    # Resolve the doctor's clinic once; we need it almost everywhere below.
    clinic = None
    try:
        clinic = Doctor.objects.select_related('clinic').get(
            whatsapp_number=state.whatsapp_number
        ).clinic
    except Doctor.DoesNotExist:
        pass

    # ── STEP 0: Date-mode preset (first screen after Set Availability) ──
    if state.step == 'choose_date_mode':
        today = date.today()
        if text_lower in ('mode_next7', '📅 next 7 days', 'next 7 days', '1'):
            dates = []
            for i in range(14):
                d = today + timedelta(days=i)
                if clinic and not clinic.is_open(d):
                    continue
                dates.append(d.isoformat())
                if len(dates) == 7:
                    break
            context['selected_dates'] = dates
            state.context = context
            state.step = 'select_session'
            state.save()
            return _morning_afternoon_buttons(), state

        if text_lower in ('mode_weekdays', '💼 weekdays only', 'weekdays only', 'weekdays', '2'):
            dates = []
            for i in range(14):
                d = today + timedelta(days=i)
                if d.weekday() >= 5:
                    continue
                if clinic and not clinic.is_open(d):
                    continue
                dates.append(d.isoformat())
                if len(dates) == 5:
                    break
            context['selected_dates'] = dates
            state.context = context
            state.step = 'select_session'
            state.save()
            return _morning_afternoon_buttons(), state

        if text_lower in ('mode_custom_dates', '🎯 pick dates', 'pick dates', 'custom', '3'):
            context['selected_dates'] = []
            state.context = context
            state.step = 'select_dates'
            state.save()
            return _next_7_days_list([], clinic), state

        # Fallback: re-show the preset buttons
        return _date_mode_buttons(), state

    if state.step == 'select_dates':
        selected = list(context.get('selected_dates', []))

        # "done" from the interactive list row
        if text_lower in ('done', '✅ done', 'skip', '⏭️ skip', 'finish', '✅ finish'):
            if not selected:
                return BotResponse.as_text("Pick at least one date first."), state
            context['selected_dates'] = selected
            state.context = context
            state.step = 'select_session'
            state.save()
            return _morning_afternoon_buttons(), state

        parsed_date = _parse_incoming_date(text_raw)
        if not parsed_date:
            return BotResponse.as_text("❌ Couldn't understand the date. Please tap from the list."), state

        if clinic and not clinic.is_open(parsed_date):
            return BotResponse.as_text(
                f"❌ {clinic.name} is closed on {parsed_date.strftime('%A %d %b')}. "
                "Please pick another date."
            ), state

        iso = parsed_date.isoformat()
        if iso in selected:
            selected.remove(iso)       # toggle off
        else:
            selected.append(iso)       # toggle on
        context['selected_dates'] = selected
        state.context = context
        state.save()
        return _next_7_days_list(selected, clinic), state

    elif state.step == 'select_session':
        session_map = {
            'morning': 'morning', '🌅 morning': 'morning', '1': 'morning',
            'afternoon': 'afternoon', '🌇 afternoon': 'afternoon', '2': 'afternoon',
            'full_day': 'full_day', 'full day': 'full_day', '📋 full day': 'full_day', '3': 'full_day',
        }
        session = session_map.get(text_lower, text_lower)
        if session not in ('morning', 'afternoon', 'full_day'):
            return _morning_afternoon_buttons(), state

        context['session'] = session
        context['selected_times'] = []
        state.context = context
        state.step = 'choose_time_mode'
        state.save()
        return _time_mode_buttons(session, len(context.get('selected_dates', []))), state

    elif state.step == 'choose_time_mode':
        session = context.get('session', 'full_day')
        ref_date = _first_selected_date(context)
        if text_lower in ('times_all', '✅ all slots', 'all slots', 'all', '1'):
            all_slots = [k for k, _ in _clinic_session_slots(clinic, ref_date, session)]
            context['selected_times'] = all_slots
            state.context = context
            state.save()
            return _save_selected_availability(state), state

        if text_lower in ('times_custom', '🎯 pick times', 'pick times', 'custom', '2'):
            state.step = 'select_slots'
            state.save()
            return _time_slots_list(clinic, ref_date, session, []), state

        return _time_mode_buttons(session, len(context.get('selected_dates', []))), state

    elif state.step == 'select_slots':
        session = context.get('session', 'full_day')
        selected_times = list(context.get('selected_times', []))
        ref_date = _first_selected_date(context)

        if text_lower in ('done', '✅ done', 'cancel', '⏭️ cancel', 'finish', '✅ finish'):
            if not selected_times:
                state.current_flow = 'doctor_menu'
                state.step = ''
                state.context = {}
                state.save()
                return _with_doctor_menu("No slots were added."), state
            return _save_selected_availability(state), state

        # Strip any checkbox marker, then match to this clinic's known slots
        text_clean = text_raw
        for marker in ('☑️ ', '☐ ', '✅ '):
            if text_clean.startswith(marker):
                text_clean = text_clean[len(marker):]
                break
        text_upper = text_clean.strip().upper()
        matched = None
        for time_key, time_display in _clinic_session_slots(clinic, ref_date, session):
            if text_upper == time_key or text_upper == time_display.upper():
                matched = time_key
                break

        if not matched:
            return BotResponse.as_text(
                "❌ That time isn't in this clinic's hours. Please tap from the list."
            ), state

        if matched in selected_times:
            selected_times.remove(matched)
        else:
            selected_times.append(matched)
        context['selected_times'] = selected_times
        state.context = context
        state.save()
        return _time_slots_list(clinic, ref_date, session, selected_times), state

    # Fallback — also handle old text-based format for backward compat
    result = parse_availability_simple(text)
    if not result:
        result = parse_availability_with_llm(text)

    if result and 'error' not in result:
        try:
            doctor = Doctor.objects.get(whatsapp_number=state.whatsapp_number)
            slot_date = datetime.strptime(result['date'], '%Y-%m-%d').date()
            created_slots = []
            for time_str in result['slots']:
                slot_time = datetime.strptime(time_str, '%H:%M').time()
                slot, created = AvailableSlot.objects.get_or_create(
                    doctor=doctor, date=slot_date, time=slot_time,
                    defaults={'is_booked': False}
                )
                if created:
                    created_slots.append(slot_time.strftime('%I:%M %p'))
            if not created_slots:
                created_slots = [datetime.strptime(t, '%H:%M').time().strftime('%I:%M %p') for t in result['slots']]

            state.current_flow = 'doctor_menu'
            state.step = ''
            state.context = {}
            state.save()

            slots_text = "\n".join(f"• {s}" for s in created_slots)
            return _with_doctor_menu(f"✅ Slots saved for {slot_date.strftime('%d-%b-%Y')}:\n{slots_text}"), state
        except Exception as e:
            logger.error(f"Error saving slots: {e}")

    return _doctor_menu_list(), state


def view_today_bookings(state):
    doctor = Doctor.objects.filter(whatsapp_number=state.whatsapp_number).first()
    if not doctor:
        return BotResponse.as_text("Error: Doctor not found."), state

    today = date.today()
    appointments = Appointment.objects.filter(
        doctor=doctor, status='booked', slot__date=today
    ).select_related('patient', 'slot').order_by('slot__time')

    state.current_flow = 'doctor_menu'
    state.step = ''
    state.context = {}
    state.save()

    if not appointments.exists():
        return _with_doctor_menu("📋 No bookings for today."), state

    bookings = "\n".join(
        f"• {a.slot.time.strftime('%I:%M %p')} — {a.patient.name} ({a.patient.whatsapp_number})"
        for a in appointments
    )
    return _with_doctor_menu(f"📋 *Today's Bookings ({today.strftime('%d-%b-%Y')}):*\n\n{bookings}"), state


def view_upcoming_bookings(state):
    doctor = Doctor.objects.filter(whatsapp_number=state.whatsapp_number).first()
    if not doctor:
        return BotResponse.as_text("Error: Doctor not found."), state

    appointments = Appointment.objects.filter(
        doctor=doctor, status='booked', slot__date__gte=date.today()
    ).select_related('patient', 'slot').order_by('slot__date', 'slot__time')

    state.current_flow = 'doctor_menu'
    state.step = ''
    state.context = {}
    state.save()

    if not appointments.exists():
        return _with_doctor_menu("📋 No upcoming bookings."), state

    from collections import OrderedDict
    by_date = OrderedDict()
    for a in appointments:
        d = a.slot.date.strftime('%d-%b-%Y')
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(f"  • {a.slot.time.strftime('%I:%M %p')} — {a.patient.name}")

    bookings = "\n".join(
        f"*{dt}:*\n" + "\n".join(items)
        for dt, items in by_date.items()
    )
    return _with_doctor_menu(f"📋 *Upcoming Bookings:*\n\n{bookings}"), state


# ─── Availability Parsing (backward compat for text input) ───────

def parse_availability_simple(text: str) -> dict:
    import re
    text_lower = text.strip().lower()
    text_lower = re.sub(r'^(available|slots?|set)\s+', '', text_lower)
    today = date.today()
    parts = re.split(r'[\s,]+', text_lower)
    parsed_date = None
    time_parts = []

    if 'tomorrow' in parts:
        parsed_date = today + timedelta(days=1)
        parts.remove('tomorrow')
    elif 'today' in parts:
        parsed_date = today
        parts.remove('today')

    if not parsed_date:
        date_formats = ['%d-%B', '%d-%b', '%d/%m', '%d-%m', '%d-%B-%Y', '%d-%b-%Y', '%d/%m/%Y', '%d-%m-%Y']
        for i in range(min(2, len(parts))):
            date_str = '-'.join(parts[:i+1])
            for fmt in date_formats:
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    if parsed.year == 1900:
                        parsed = parsed.replace(year=today.year)
                        if parsed.date() < today:
                            parsed = parsed.replace(year=today.year + 1)
                    parsed_date = parsed.date()
                    parts = parts[i+1:]
                    break
                except ValueError:
                    continue
            if parsed_date:
                break

    if not parsed_date:
        return None

    time_pattern = re.compile(r'(\d{1,2}):?(\d{2})?\s*(am|pm)?', re.IGNORECASE)
    for part in parts:
        match = time_pattern.match(part)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            period = (match.group(3) or '').lower()
            if period == 'pm' and hour != 12:
                hour += 12
            elif period == 'am' and hour == 12:
                hour = 0
            time_parts.append(f"{hour:02d}:{minute:02d}")

    if not time_parts:
        return None
    return {'date': parsed_date.isoformat(), 'slots': time_parts}


def parse_availability_with_llm(text: str) -> dict:
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        prompt = AVAILABILITY_PARSE_PROMPT.format(today=date.today().isoformat(), message=text)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0, max_tokens=200,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Groq availability parsing failed: {e}")
        return None
