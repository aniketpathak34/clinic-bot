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


def _next_7_days_list():
    """Interactive list of next 7 days for date selection."""
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    today = date.today()
    rows = []
    for i in range(7):
        d = today + timedelta(days=i)
        day = day_names[d.weekday()]
        label = "Today" if i == 0 else ("Tomorrow" if i == 1 else f"{day}, {d.strftime('%d %b')}")

        # Show existing slot count
        existing = AvailableSlot.objects.filter(
            doctor__whatsapp_number__isnull=False,  # will be filtered by caller
            date=d
        ).count()

        rows.append({
            "id": d.isoformat(),
            "title": label,
            "description": d.strftime('%d %B %Y'),
        })

    return BotResponse.as_list(
        "📅 Select a date to set your availability:",
        "Choose Date",
        rows
    )


def _morning_afternoon_buttons():
    """Buttons to choose morning or afternoon session."""
    return BotResponse.as_buttons(
        "Which session do you want to set?",
        [
            {"id": "morning", "title": "🌅 Morning"},
            {"id": "afternoon", "title": "🌇 Afternoon"},
            {"id": "full_day", "title": "📋 Full Day"},
        ]
    )


def _time_slots_list(session):
    """List of time slots based on session."""
    if session == 'morning':
        slots = [(k, v) for k, v in TIME_SLOTS if int(k.split(':')[0]) < 13]
        body = "🌅 Select your morning slots:"
    elif session == 'afternoon':
        slots = [(k, v) for k, v in TIME_SLOTS if int(k.split(':')[0]) >= 13]
        body = "🌇 Select your afternoon/evening slots:"
    else:
        slots = TIME_SLOTS
        body = "📋 Select your slots:"

    # WhatsApp list max 10 rows — split if needed
    rows = [{"id": k, "title": v} for k, v in slots[:10]]
    return BotResponse.as_list(body, "Choose Time", rows)


# ─── Flow Handlers ───────────────────────────────────────────────

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
        state.step = 'select_date'
        state.context = {}
        state.save()
        return _next_7_days_list(), state

    elif choice == '2':
        return view_today_bookings(state)

    elif choice == '3':
        return view_upcoming_bookings(state)

    else:
        return _doctor_menu_list(), state


def handle_set_availability(state, text):
    """Interactive availability setting flow."""
    context = state.context or {}

    if state.step == 'select_date':
        # Parse the selected date
        selected_date = None

        # Try ISO format (from interactive list id)
        try:
            selected_date = datetime.strptime(text.strip(), '%Y-%m-%d').date()
        except ValueError:
            pass

        # Try common formats
        if not selected_date:
            text_lower = text.strip().lower()
            today = date.today()
            if text_lower == 'today':
                selected_date = today
            elif text_lower == 'tomorrow':
                selected_date = today + timedelta(days=1)
            else:
                # Try title format like "Mon, 23 Mar" or "23 March 2026"
                clean = text.strip()
                if ', ' in clean:
                    clean = clean.split(', ', 1)[1]
                for fmt in ['%d %b', '%d %B', '%d %b %Y', '%d %B %Y', '%d-%b-%Y']:
                    try:
                        parsed = datetime.strptime(clean, fmt)
                        if parsed.year == 1900:
                            parsed = parsed.replace(year=today.year)
                        selected_date = parsed.date()
                        break
                    except ValueError:
                        continue

        if not selected_date:
            return BotResponse.as_text("❌ Couldn't understand the date. Please try again."), state

        context['date'] = selected_date.isoformat()
        context['date_display'] = selected_date.strftime('%d-%b-%Y')
        state.context = context
        state.step = 'select_session'
        state.save()
        return _morning_afternoon_buttons(), state

    elif state.step == 'select_session':
        session = text.strip().lower()
        # Map button titles to session IDs
        session_map = {
            'morning': 'morning', '🌅 morning': 'morning', '1': 'morning',
            'afternoon': 'afternoon', '🌇 afternoon': 'afternoon', '2': 'afternoon',
            'full_day': 'full_day', 'full day': 'full_day', '📋 full day': 'full_day', '3': 'full_day',
        }
        session = session_map.get(session, session)

        if session not in ('morning', 'afternoon', 'full_day'):
            return _morning_afternoon_buttons(), state

        context['session'] = session
        state.context = context
        state.step = 'select_slots'
        state.save()
        return _time_slots_list(session), state

    elif state.step == 'select_slots':
        # Doctor picks one slot at a time
        # Find matching time slot
        selected_time = None
        text_clean = text.strip().upper()

        # Match by ID (HH:MM) or title (HH:MM AM/PM)
        for time_key, time_display in TIME_SLOTS:
            if text_clean == time_key or text_clean == time_display.upper():
                selected_time = time_key
                break

        if not selected_time:
            return BotResponse.as_text("❌ Invalid time. Please select from the list."), state

        # Save this slot
        doctor = Doctor.objects.get(whatsapp_number=state.whatsapp_number)
        slot_date = datetime.strptime(context['date'], '%Y-%m-%d').date()
        slot_time = datetime.strptime(selected_time, '%H:%M').time()

        slot, created = AvailableSlot.objects.get_or_create(
            doctor=doctor, date=slot_date, time=slot_time,
            defaults={'is_booked': False}
        )

        # Track added slots
        added = context.get('added_slots', [])
        time_display = slot_time.strftime('%I:%M %p')
        if time_display not in added:
            added.append(time_display)
        context['added_slots'] = added
        state.context = context
        state.save()

        # Ask if they want to add more or finish
        added_text = ", ".join(added)
        state.step = 'add_more_or_done'
        state.save()

        return BotResponse.as_buttons(
            f"✅ Added {time_display}\n\n"
            f"Slots for {context['date_display']}: {added_text}\n\n"
            f"Add more slots?",
            [
                {"id": "more", "title": "➕ Add More"},
                {"id": "done", "title": "✅ Done"},
            ]
        ), state

    elif state.step == 'add_more_or_done':
        choice = text.strip().lower()
        choice_map = {
            'more': 'more', '➕ add more': 'more', 'add more': 'more', '1': 'more',
            'done': 'done', '✅ done': 'done', '2': 'done',
        }
        choice = choice_map.get(choice, choice)

        if choice == 'more':
            state.step = 'select_slots'
            state.save()
            session = context.get('session', 'full_day')
            return _time_slots_list(session), state
        else:
            # Done — show summary and return to menu
            added = context.get('added_slots', [])
            date_display = context.get('date_display', '')
            slots_text = "\n".join(f"• {s}" for s in added)

            state.current_flow = 'doctor_menu'
            state.step = ''
            state.context = {}
            state.save()

            return _with_doctor_menu(
                f"✅ Availability set for {date_display}:\n{slots_text}\n\n"
                f"Total: {len(added)} slots"
            ), state

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
