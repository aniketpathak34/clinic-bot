"""Natural language processing using Groq (Llama 3.3) for understanding user messages."""
import json
import logging
from datetime import date, timedelta

from django.conf import settings

logger = logging.getLogger(__name__)


def parse_menu_choice(text: str, language: str) -> str:
    """Parse natural language menu selection into a menu number.

    Returns '1'-'5' if understood, or None if not.
    """
    text_lower = text.strip().lower()

    # Quick check — if it's already a number, return it
    if text_lower in ('1', '2', '3', '4', '5'):
        return text_lower

    # Keyword matching first (fast, no API call)
    booking_keywords = ['book', 'appointment', 'schedule', 'new',
                        'बुक', 'अपॉइंटमेंट', 'नई',  # Hindi
                        'बुक करा', 'अपॉइंटमेंट बुक', 'नवीन',  # Marathi
                        'book karo', 'appointment lena', 'book karaychi',
                        'appointment book', 'book kara', 'navin']
    reschedule_keywords = ['reschedule', 'change', 'shift', 'move',
                           'बदलें', 'बदला', 'बदल',
                           'badal', 'badla', 'change karo', 'shift karo']
    cancel_keywords = ['cancel', 'delete', 'remove', 'hatao',
                       'रद्द', 'कैंसल', 'हटाओ',
                       'cancel karo', 'radd kara', 'radd', 'cancel kara']
    view_keywords = ['view', 'show', 'my appointment', 'list', 'check', 'status',
                     'मेरी', 'दिखाओ', 'माझ्या', 'दाखवा',
                     'dikhao', 'dikhav', 'dikha', 'dekho', 'dakhva', 'dakhav',
                     'majhya', 'majhi', 'meri appointment', 'mazi']
    enquiry_keywords = ['enquiry', 'query', 'question', 'ask', 'help', 'info',
                        'पूछताछ', 'सवाल', 'मदद', 'चौकशी', 'प्रश्न',
                        'puchho', 'sawal', 'madad', 'chaukashi', 'vichar']

    # Check cancel/reschedule BEFORE booking (since "cancel appointment" contains "appointment")
    for kw in cancel_keywords:
        if kw in text_lower:
            return '3'
    for kw in reschedule_keywords:
        if kw in text_lower:
            return '2'
    for kw in view_keywords:
        if kw in text_lower:
            return '4'
    for kw in enquiry_keywords:
        if kw in text_lower:
            return '5'
    for kw in booking_keywords:
        if kw in text_lower:
            return '1'

    # Fallback to LLM
    return _llm_parse_menu(text, language)


def parse_natural_date(text: str, language: str) -> date:
    """Parse natural language date from any language.

    Handles: "tomorrow", "udya", "kal", "next monday", "parso",
             "22-march", "22/03/2026", etc.
    Returns a date object or None.
    """
    text_lower = text.strip().lower()

    # Quick keyword matching (no API call)
    today = date.today()

    # Tomorrow in multiple languages
    tomorrow_words = ['tomorrow', 'kal', 'udya', 'उद्या', 'कल']
    for word in tomorrow_words:
        if word in text_lower:
            return today + timedelta(days=1)

    # Today
    today_words = ['today', 'aaj', 'aaj', 'आज']
    for word in today_words:
        if word in text_lower:
            return today

    # Day after tomorrow
    dayafter_words = ['day after tomorrow', 'parso', 'parwa', 'परसों', 'परवा']
    for word in dayafter_words:
        if word in text_lower:
            return today + timedelta(days=2)

    # Try standard date formats first
    from apps.conversations.nodes.patient_nodes import parse_date
    parsed = parse_date(text)
    if parsed:
        return parsed

    # Fallback to LLM for complex cases
    return _llm_parse_date(text, language)


def _llm_parse_menu(text: str, language: str) -> str:
    """Use Groq to understand menu intent from natural language."""
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return None

    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        prompt = f"""You are a clinic appointment bot. The user sent a message in {language} language.
Determine which menu option they want:
1 = Book new appointment
2 = Reschedule existing appointment
3 = Cancel appointment
4 = View my appointments
5 = Enquiry / ask a question

User message: "{text}"

Reply with ONLY a JSON object: {{"choice": "1"}} or {{"choice": "2"}} etc.
If you cannot determine the intent, reply: {{"choice": null}}"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=50,
        )

        result = json.loads(response.choices[0].message.content)
        choice = result.get('choice')
        if choice in ('1', '2', '3', '4', '5'):
            return choice
        return None

    except Exception as e:
        logger.error(f"LLM menu parsing failed: {e}")
        return None


def _llm_parse_date(text: str, language: str) -> date:
    """Use Groq to parse natural language date."""
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return None

    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        prompt = f"""You are a date parser. Today is {date.today().isoformat()}.
The user sent a message in {language} language that contains a date reference.
Extract the date they mean.

User message: "{text}"

Reply with ONLY a JSON object: {{"date": "YYYY-MM-DD"}}
If you cannot determine a date, reply: {{"date": null}}"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=50,
        )

        result = json.loads(response.choices[0].message.content)
        date_str = result.get('date')
        if date_str:
            from datetime import datetime
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        return None

    except Exception as e:
        logger.error(f"LLM date parsing failed: {e}")
        return None
