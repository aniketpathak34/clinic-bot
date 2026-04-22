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

# Common clinic time slots
TIME_SLOTS = [
    ("09:00", "09:00 AM"),
    ("09:30", "09:30 AM"),
    ("10:00", "10:00 AM"),
    ("10:30", "10:30 AM"),
    ("11:00", "11:00 AM"),
    ("11:30", "11:30 AM"),
    ("12:00", "12:00 PM"),
    ("12:30", "12:30 PM"),
    ("14:00", "02:00 PM"),
    ("14:30", "02:30 PM"),
    ("15:00", "03:00 PM"),
    ("15:30", "03:30 PM"),
    ("16:00", "04:00 PM"),
    ("16:30", "04:30 PM"),
    ("17:00", "05:00 PM"),
    ("17:30", "05:30 PM"),
    ("18:00", "06:00 PM"),
    ("18:30", "06:30 PM"),
    ("19:00", "07:00 PM"),
    ("19:30", "07:30 PM"),
    ("20:00", "08:00 PM"),
]


# ─── Interactive Response Builders ───────────────────────────────

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


def _next_7_days_list(selected_dates: list = None):
    """Interactive list of next 7 days. Tap-to-toggle multi-select.

    ✅ prefix marks already-selected dates; the last row is "✅ Done" to
    finalize. WhatsApp hard-caps list rows at 10, so 7 days + Done fits.
    """
    selected_dates = selected_dates or []
    selected_set = set(selected_dates)

    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    today = date.today()
    rows = []
    for i in range(7):
        d = today + timedelta(days=i)
        day = day_names[d.weekday()]
        label = "Today" if i == 0 else ("Tomorrow" if i == 1 else f"{day}, {d.strftime('%d %b')}")
        prefix = "✅ " if d.isoformat() in selected_set else ""
        rows.append({
            "id": d.isoformat(),
            "title": (prefix + label)[:24],   # WhatsApp row title max 24 chars
            "description": d.strftime('%d %B %Y'),
        })

    rows.append({
        "id": "done",
        "title": "✅ Done" if selected_set else "⏭️ Skip",
        "description": f"{len(selected_set)} date(s) selected" if selected_set else "Pick at least one date first",
    })

    if selected_set:
        summary = ", ".join(sorted(selected_set))
        body = f"📅 Pick your available dates — tap to toggle.\n\n*Selected:* {summary}"
    else:
        body = "📅 Pick the dates you are available.\nTap a date to add it, then tap it again to remove.\nTap *Done* when finished."

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


def _time_slots_list(session: str, selected_times: list = None):
    """Interactive slot list with multi-select toggle + Done row."""
    selected_times = selected_times or []
    selected_set = set(selected_times)

    if session == 'morning':
        slots = [(k, v) for k, v in TIME_SLOTS if int(k.split(':')[0]) < 13]
        body_prefix = "🌅 Morning slots"
    elif session == 'afternoon':
        slots = [(k, v) for k, v in TIME_SLOTS if int(k.split(':')[0]) >= 13]
        body_prefix = "🌇 Afternoon/evening slots"
    else:
        slots = TIME_SLOTS
        body_prefix = "📋 Slots"

    # Reserve one row for Done ⇒ max 9 time slots displayed on screen.
    slots = slots[:9]

    rows = []
    for k, v in slots:
        prefix = "✅ " if k in selected_set else ""
        rows.append({"id": k, "title": (prefix + v)[:24]})

    rows.append({
        "id": "done",
        "title": "✅ Done" if selected_set else "⏭️ Cancel",
        "description": f"{len(selected_set)} time(s) selected" if selected_set else "Pick at least one slot first",
    })

    if selected_set:
        summary = ", ".join(
            v for k, v in TIME_SLOTS if k in selected_set
        )
        body = f"{body_prefix} — tap to toggle.\n\n*Selected:* {summary}"
    else:
        body = f"{body_prefix}\nTap slots to add, tap again to remove.\nTap *Done* when finished."

    return BotResponse.as_list(body, "Choose Times", rows)


# ─── Flow Handlers ───────────────────────────────────────────────

def _parse_incoming_date(text: str):
    """Return a date from an ISO string, 'today'/'tomorrow', or a title like
    'Mon, 23 Apr'. Falls through common strptime formats. Returns None on fail.
    Leading emoji checkmark from a toggled row is stripped.
    """
    t = text.strip()
    if t.startswith('✅ '):
        t = t[2:].strip()
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
    Resets state to doctor menu and returns a summary BotResponse.
    """
    context = state.context or {}
    doctor = Doctor.objects.get(whatsapp_number=state.whatsapp_number)

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
    for d in selected_dates:
        for t in selected_times:
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
    skipped = f" ({existed} already existed)" if existed else ""
    return _with_doctor_menu(
        f"✅ *Availability saved*\n\n"
        f"📅 Dates: {date_labels}\n"
        f"🕐 Times: {time_labels}\n\n"
        f"Total new slots: *{created}*{skipped}"
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
        state.step = 'select_dates'
        state.context = {'selected_dates': []}
        state.save()
        return _next_7_days_list([]), state

    elif choice == '2':
        return view_today_bookings(state)

    elif choice == '3':
        return view_upcoming_bookings(state)

    else:
        return _doctor_menu_list(), state


def handle_set_availability(state, text):
    """Interactive availability setting flow — multi-select dates + times."""
    context = state.context or {}
    text_raw = text.strip()
    text_lower = text_raw.lower()

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

        iso = parsed_date.isoformat()
        if iso in selected:
            selected.remove(iso)       # toggle off
        else:
            selected.append(iso)       # toggle on
        context['selected_dates'] = selected
        state.context = context
        state.save()
        return _next_7_days_list(selected), state

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
        state.step = 'select_slots'
        state.save()
        return _time_slots_list(session, []), state

    elif state.step == 'select_slots':
        session = context.get('session', 'full_day')
        selected_times = list(context.get('selected_times', []))

        if text_lower in ('done', '✅ done', 'cancel', '⏭️ cancel', 'finish', '✅ finish'):
            if not selected_times:
                # Abort cleanly — no slots picked yet
                state.current_flow = 'doctor_menu'
                state.step = ''
                state.context = {}
                state.save()
                return _with_doctor_menu("No slots were added."), state
            return _save_selected_availability(state), state

        # Match by ID (HH:MM) or title (HH:MM AM/PM)
        text_upper = text_raw.upper()
        matched = None
        for time_key, time_display in TIME_SLOTS:
            if text_upper == time_key or text_upper == time_display.upper() \
               or text_upper == ("✅ " + time_display).upper():
                matched = time_key
                break

        if not matched:
            return BotResponse.as_text("❌ Invalid time. Please tap from the list."), state

        if matched in selected_times:
            selected_times.remove(matched)
        else:
            selected_times.append(matched)
        context['selected_times'] = selected_times
        state.context = context
        state.save()
        return _time_slots_list(session, selected_times), state

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
