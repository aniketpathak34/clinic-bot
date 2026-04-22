"""Multi-language message templates for the clinic bot."""

MESSAGES = {
    "en": {
        # Language selection
        "welcome": "Welcome! Please choose your language:\n1. English\n2. हिंदी (Hindi)\n3. मराठी (Marathi)",

        # Patient registration
        "need_registration": "To book an appointment, we need a few details first.",
        "ask_name": "What is your name?",
        "ask_age": "Nice to meet you, {name}! What is your age?",
        "registration_complete": "Registration complete! Welcome, {name}.",

        # Main menu
        "main_menu": (
            "How can I help you today?\n\n"
            "1. 📅 Book Appointment\n"
            "2. 🔄 Reschedule Appointment\n"
            "3. ❌ Cancel Appointment\n"
            "4. 📋 My Appointments\n"
            "5. ❓ Enquiry"
        ),

        # Booking
        "select_doctor": "Available doctors:\n{doctors}\n\nPlease reply with the doctor number.",
        "select_date": "Please enter the date for your appointment (e.g., 25-march or 25-03-2026):",
        "select_slot": "Available slots for Dr. {doctor} on {date}:\n{slots}\n\nPlease reply with the slot number.",
        "no_slots": "Sorry, no available slots for Dr. {doctor} on {date}. Please try another date.",
        "booking_confirmed": "✅ Appointment booked!\n\nDoctor: Dr. {doctor}\nDate: {date}\nTime: {time}\n\nYou will receive a reminder before your appointment.",
        "no_doctors": "Sorry, no doctors are available at this clinic currently.",

        # Cancel
        "select_appointment_cancel": "Your upcoming appointments:\n{appointments}\n\nReply with the number to cancel, or 0 to go back.",
        "cancel_confirmed": "✅ Your appointment with Dr. {doctor} on {date} at {time} has been cancelled.",
        "no_appointments": "You have no upcoming appointments.",

        # Reschedule
        "select_appointment_reschedule": "Your upcoming appointments:\n{appointments}\n\nReply with the number to reschedule, or 0 to go back.",
        "reschedule_select_date": "Please enter the new date (e.g., 25-march or 25-03-2026):",
        "reschedule_confirmed": "✅ Appointment rescheduled!\n\nDoctor: Dr. {doctor}\nNew Date: {date}\nNew Time: {time}",

        # View appointments
        "upcoming_appointments": "Your upcoming appointments:\n{appointments}",

        # Enquiry
        "enquiry_prompt": "What would you like to know? Type your question:",
        "enquiry_default": "For more details, please contact the clinic directly. Send 'menu' to go back.",

        # General
        "invalid_input": "Sorry, I didn't understand that. Please try again.",
        "back_to_menu": "Send 'menu' to see the main menu.",
        "error": "Something went wrong. Please try again or send 'reset' to start over.",

        # Doctor messages
        "doctor_welcome": "Welcome, Doctor! Please enter your clinic code to register:",
        "doctor_ask_name": "What is your name?",
        "doctor_ask_specialty": (
            "What is your specialty?\n"
            "1. General Physician\n"
            "2. Dentist\n"
            "3. Gynecologist\n"
            "4. Pediatrician\n"
            "5. Dermatologist\n"
            "6. ENT Specialist\n"
            "7. Orthopedic\n"
            "8. Other"
        ),
        "doctor_registration_complete": "✅ Registration complete! Welcome, Dr. {name}.",
        "doctor_invalid_clinic": "❌ Invalid clinic code. Please try again:",
        "doctor_menu": (
            "Doctor Menu:\n\n"
            "1. 📅 Set Availability\n"
            "2. 📋 View Today's Bookings\n"
            "3. 📊 View All Upcoming Bookings"
        ),
        "doctor_availability_prompt": "Send your available slots like:\navailable 25-march 10am 11am 2pm 4pm",
        "doctor_slots_saved": "✅ Slots saved for {date}:\n{slots}",
        "doctor_slots_parse_error": "❌ Couldn't understand the format. Please try:\navailable 25-march 10am 11am 2pm 4pm",
        "doctor_today_bookings": "Today's bookings:\n{bookings}",
        "doctor_no_bookings": "No bookings for today.",
        "doctor_upcoming_bookings": "Upcoming bookings:\n{bookings}",
        "doctor_welcome_onboarded": (
            "👋 Welcome, Dr. {name}!\n\n"
            "You have been added to *{clinic_name}* on our WhatsApp booking bot.\n\n"
            "From this number you can:\n"
            "• 📅 Set your availability\n"
            "• 📋 View today's bookings\n"
            "• 📊 See upcoming appointments\n\n"
            "Patients who book with {clinic_name} will automatically appear in your list, "
            "and you'll get an instant alert here for every new booking.\n\n"
            "Reply *hi* to see your menu."
        ),
        "doctor_new_booking_notification": "🔔 New appointment!\nPatient: {patient}\nDate: {date}\nTime: {time}",
        "doctor_cancel_notification": "❌ Appointment cancelled!\nPatient: {patient}\nDate: {date}\nTime: {time}\n\nThe slot is now available again.",
        "call_confirmed": "✅ Your appointment with Dr. {doctor} on {date} at {time} is confirmed. See you there!",
    },

    "hi": {
        "welcome": "स्वागत है! कृपया अपनी भाषा चुनें:\n1. English\n2. हिंदी (Hindi)\n3. मराठी (Marathi)",
        "need_registration": "अपॉइंटमेंट बुक करने के लिए, हमें कुछ जानकारी चाहिए।",
        "ask_name": "आपका नाम क्या है?",
        "ask_age": "आपसे मिलकर अच्छा लगा, {name}! आपकी उम्र क्या है?",
        "registration_complete": "पंजीकरण पूरा हुआ! स्वागत है, {name}।",
        "main_menu": (
            "मैं आपकी कैसे मदद कर सकता हूँ?\n\n"
            "1. 📅 अपॉइंटमेंट बुक करें\n"
            "2. 🔄 अपॉइंटमेंट बदलें\n"
            "3. ❌ अपॉइंटमेंट रद्द करें\n"
            "4. 📋 मेरी अपॉइंटमेंट\n"
            "5. ❓ पूछताछ"
        ),
        "select_doctor": "उपलब्ध डॉक्टर:\n{doctors}\n\nकृपया डॉक्टर का नंबर भेजें।",
        "select_date": "कृपया अपॉइंटमेंट की तारीख बताएं (जैसे: 25-march या 25-03-2026):",
        "select_slot": "Dr. {doctor} की {date} को उपलब्ध समय:\n{slots}\n\nकृपया समय का नंबर भेजें।",
        "no_slots": "माफ़ कीजिए, Dr. {doctor} के पास {date} को कोई समय उपलब्ध नहीं है।",
        "booking_confirmed": "✅ अपॉइंटमेंट बुक हो गई!\n\nडॉक्टर: Dr. {doctor}\nतारीख: {date}\nसमय: {time}\n\nआपको अपॉइंटमेंट से पहले रिमाइंडर मिलेगा।",
        "no_doctors": "माफ़ कीजिए, अभी कोई डॉक्टर उपलब्ध नहीं हैं।",
        "select_appointment_cancel": "आपकी आगामी अपॉइंटमेंट:\n{appointments}\n\nरद्द करने के लिए नंबर भेजें, या वापस जाने के लिए 0 भेजें।",
        "cancel_confirmed": "✅ Dr. {doctor} के साथ {date} को {time} बजे की अपॉइंटमेंट रद्द कर दी गई।",
        "no_appointments": "आपकी कोई आगामी अपॉइंटमेंट नहीं है।",
        "select_appointment_reschedule": "आपकी आगामी अपॉइंटमेंट:\n{appointments}\n\nबदलने के लिए नंबर भेजें, या वापस जाने के लिए 0 भेजें।",
        "reschedule_select_date": "कृपया नई तारीख बताएं (जैसे: 25-march या 25-03-2026):",
        "reschedule_confirmed": "✅ अपॉइंटमेंट बदल दी गई!\n\nडॉक्टर: Dr. {doctor}\nनई तारीख: {date}\nनया समय: {time}",
        "upcoming_appointments": "आपकी आगामी अपॉइंटमेंट:\n{appointments}",
        "enquiry_prompt": "आप क्या जानना चाहते हैं? अपना सवाल लिखें:",
        "enquiry_default": "अधिक जानकारी के लिए कृपया क्लिनिक से संपर्क करें। मेनू के लिए 'menu' भेजें।",
        "invalid_input": "माफ़ कीजिए, मैं समझ नहीं पाया। कृपया फिर से कोशिश करें।",
        "back_to_menu": "मुख्य मेनू के लिए 'menu' भेजें।",
        "error": "कुछ गलत हो गया। कृपया फिर से कोशिश करें या 'reset' भेजें।",
    },

    "mr": {
        "welcome": "स्वागत! कृपया तुमची भाषा निवडा:\n1. English\n2. हिंदी (Hindi)\n3. मराठी (Marathi)",
        "need_registration": "अपॉइंटमेंट बुक करण्यासाठी, आम्हाला काही माहिती हवी आहे.",
        "ask_name": "तुमचे नाव काय आहे?",
        "ask_age": "भेटून आनंद झाला, {name}! तुमचे वय किती आहे?",
        "registration_complete": "नोंदणी पूर्ण! स्वागत, {name}.",
        "main_menu": (
            "मी तुम्हाला कशी मदत करू शकतो?\n\n"
            "1. 📅 अपॉइंटमेंट बुक करा\n"
            "2. 🔄 अपॉइंटमेंट बदला\n"
            "3. ❌ अपॉइंटमेंट रद्द करा\n"
            "4. 📋 माझ्या अपॉइंटमेंट\n"
            "5. ❓ चौकशी"
        ),
        "select_doctor": "उपलब्ध डॉक्टर:\n{doctors}\n\nकृपया डॉक्टरचा क्रमांक पाठवा.",
        "select_date": "कृपया अपॉइंटमेंटची तारीख सांगा (उदा: 25-march किंवा 25-03-2026):",
        "select_slot": "Dr. {doctor} यांची {date} रोजी उपलब्ध वेळ:\n{slots}\n\nकृपया वेळेचा क्रमांक पाठवा.",
        "no_slots": "माफ करा, Dr. {doctor} यांच्याकडे {date} रोजी वेळ उपलब्ध नाही.",
        "booking_confirmed": "✅ अपॉइंटमेंट बुक झाली!\n\nडॉक्टर: Dr. {doctor}\nतारीख: {date}\nवेळ: {time}\n\nतुम्हाला अपॉइंटमेंटपूर्वी रिमाइंडर मिळेल.",
        "no_doctors": "माफ करा, सध्या कोणताही डॉक्टर उपलब्ध नाही.",
        "select_appointment_cancel": "तुमच्या आगामी अपॉइंटमेंट:\n{appointments}\n\nरद्द करण्यासाठी क्रमांक पाठवा, किंवा परत जाण्यासाठी 0 पाठवा.",
        "cancel_confirmed": "✅ Dr. {doctor} यांच्यासोबत {date} रोजी {time} वाजताची अपॉइंटमेंट रद्द झाली.",
        "no_appointments": "तुमची कोणतीही आगामी अपॉइंटमेंट नाही.",
        "select_appointment_reschedule": "तुमच्या आगामी अपॉइंटमेंट:\n{appointments}\n\nबदलण्यासाठी क्रमांक पाठवा, किंवा परत जाण्यासाठी 0 पाठवा.",
        "reschedule_select_date": "कृपया नवीन तारीख सांगा (उदा: 25-march किंवा 25-03-2026):",
        "reschedule_confirmed": "✅ अपॉइंटमेंट बदलली!\n\nडॉक्टर: Dr. {doctor}\nनवीन तारीख: {date}\nनवीन वेळ: {time}",
        "upcoming_appointments": "तुमच्या आगामी अपॉइंटमेंट:\n{appointments}",
        "enquiry_prompt": "तुम्हाला काय जाणून घ्यायचे आहे? तुमचा प्रश्न लिहा:",
        "enquiry_default": "अधिक माहितीसाठी कृपया क्लिनिकशी संपर्क साधा. मेनूसाठी 'menu' पाठवा.",
        "invalid_input": "माफ करा, मला समजले नाही. कृपया पुन्हा प्रयत्न करा.",
        "back_to_menu": "मुख्य मेनूसाठी 'menu' पाठवा.",
        "error": "काहीतरी चूक झाली. कृपया पुन्हा प्रयत्न करा किंवा 'reset' पाठवा.",
    },
}


def get_msg(lang: str, key: str, **kwargs) -> str:
    """Get a localized message. Falls back to English if key not found."""
    lang_msgs = MESSAGES.get(lang, MESSAGES["en"])
    template = lang_msgs.get(key, MESSAGES["en"].get(key, ""))
    try:
        return template.format(**kwargs) if kwargs else template
    except KeyError:
        return template
