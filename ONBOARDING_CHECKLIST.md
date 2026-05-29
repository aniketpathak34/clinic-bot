# Clinic Onboarding Checklist — DocPing

End-to-end steps to bring a new clinic live on the DocPing bot. Follow top to bottom. Time estimates are realistic.

**Total active work: ~45 min spread across 2 days. Most time is waiting for Meta approvals.**

---

## Phase 1 — Collect from the clinic (do this first, before touching Meta)

Send the clinic this list. Don't start any Meta steps until all items are returned.

### Required

| Item | Format | Notes |
|---|---|---|
| **Clinic display name** | Max 25 chars | What patients see as the WhatsApp sender. Must be the real clinic name, no promo words. Example: `Alpha Care Physio` |
| **Business category** | Pick one | `Medical and health` is the default — confirm with clinic |
| **Business description** | Max 512 chars | One line about what they do. Example: *"Physiotherapy and rehab clinic in Pune. Open Mon–Sat, 9 AM – 7 PM."* |
| **Email** | One address | For patient queries — clinic-owned, not yours |
| **WhatsApp phone number** | +91 XXXXX XXXXX | **Critical: must NOT be currently active on regular WhatsApp anywhere else.** If it is, ask them to first uninstall WhatsApp on that number, OR get a new SIM. |
| **Google Maps URL** | Short URL preferred | Example: `https://maps.app.goo.gl/AbCdEf123` — they get this from the Google Maps app → Share → Copy link |
| **Doctor list** | Name + specialty + WhatsApp number | Each doctor's own personal WhatsApp (for daily summaries, query forwarding) |
| **Operating hours** | Per day | Used for slot generation |
| **Languages** | List | Default: English. Optional: Hindi / Marathi / Bengali / Khasi. Each extra language = one set of templates approved separately. |

### Optional but recommended

| Item | Format |
|---|---|
| **Logo** | Square PNG/JPG, min 500×500 px — used as WhatsApp profile picture |
| **Business address** | Text — shown in WhatsApp business profile |
| **Website** | If they have one |
| **Intake form questions** | If they want patients to fill an intake form post-booking (Google Form route) |

---

## Phase 2 — Meta-side setup

Done from `business.facebook.com` while logged in as DocPing's admin.

### Step 1 — Add the clinic's phone number to a new WABA

1. Go to **https://business.facebook.com/wa/manage/phone-numbers**
2. Top-right → **Add phone number**
3. Fill in:
   - **WhatsApp Business display name:** the clinic's display name
   - **Timezone:** Asia/Kolkata
   - **Category:** Medical and health
   - **Description:** the clinic's description
4. Next → enter the clinic's phone number (country code +91)
5. **Verify by SMS** (or Voice if SMS fails)
6. Enter the OTP received on the clinic's phone (you'll need to coordinate — clinic owner reads it to you, or they enter it themselves)
7. Verified ✅

**A new WABA is created automatically for this clinic. Note its WABA ID.**

### Step 2 — Register the phone number with Cloud API

Phone shows "Pending" after OTP. Run this curl to register it:

```bash
curl -X POST \
  "https://graph.facebook.com/v21.0/<PHONE_NUMBER_ID>/register" \
  -H "Authorization: Bearer <PRODUCTION_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"messaging_product":"whatsapp","pin":"<6-DIGIT-PIN>"}'
```

- `<PHONE_NUMBER_ID>` = shown in WhatsApp Manager after adding the number
- `<PRODUCTION_TOKEN>` = your reusable system user token (the one that starts `EAAG…`)
- `<6-DIGIT-PIN>` = pick any non-trivial 6-digit number (avoid `123456`, `000000`). Save it in your records — needed for future re-verification.

**Expected response:** `{"success":true}`

Refresh WhatsApp Manager → status flips to **Connected** within a minute.

### Step 3 — Wait for display name approval

After Step 1, Meta reviews the display name. Typical wait: **15 min – 24 hours**.

- Check status: WhatsApp Manager → Phone Numbers → click the number → Profile tab → "Display name" should say **Approved**.
- If rejected, Meta will say why (usually display name contains promo words, brand it doesn't recognise, etc.) → fix and resubmit.

You can skip this wait and continue with Steps 4 and 5 in parallel.

### Step 4 — Assign new WABA to your system user (token stays the same)

1. Go to **https://business.facebook.com/settings/system-users**
2. Click **Aniket** (the system user you created earlier)
3. **Add Assets** → choose **WhatsApp accounts** → select the **new clinic's WABA** → toggle **Full control** → Save
4. **You don't need to generate a new token.** Your existing permanent token now works for this new WABA too.

### Step 5 — Subscribe the webhook for the new WABA

1. **developers.facebook.com → DocPing app → WhatsApp → Configuration**
2. At the top, **WhatsApp Business Account dropdown** → switch to the new clinic's WABA
3. Confirm callback URL and verify token (these don't change per WABA — they're app-level)
4. In **Webhook fields**, click **Manage** → ensure `messages` is **Subscribed** for this WABA

### Step 6 — Submit the 2 message templates (per WABA)

Each clinic's WABA needs its own template approvals. Submit both:

#### Template 1 — `reminder_day_before`

- Category: **Utility** → Default
- Body:
  ```
  Hi {{1}}, friendly reminder 🔔

  Your appointment with *{{2}}* is *tomorrow at {{3}}*.

  Reply CONFIRM to confirm, or RESCHEDULE if you need a different slot.

  See you soon!
  ```
- Samples: `{{1}}=Priya Shah` · `{{2}}=Dr. Rohan Patel` · `{{3}}=10:30 AM`

#### Template 2 — `reminder_one_hour`

- Category: **Utility** → Default
- Body:
  ```
  Hi {{1}} 👋

  Your appointment is *in 1 hour* at *{{2}}* with *{{3}}*.

  📍 Directions: {{4}}

  See you soon!
  ```
- Samples: `{{1}}=Priya Shah` · `{{2}}=10:30 AM` · `{{3}}=Dr. Rohan Patel` · `{{4}}=https://maps.app.goo.gl/exampleAbc123`

Both approve in 1–24 hours. Status → **Approved** in templates list.

---

## Phase 3 — DocPing-side configuration

Done from DocPing admin (`/admin/`).

### Step 7 — Create the Clinic record

Admin → **Clinics → Add Clinic**:

- **Name:** the clinic's name (e.g., "Alpha Care Physio Pune")
- **Display name (WhatsApp):** same as Meta display name
- **Slug:** auto-generated or set manually
- **Phone number ID:** from Step 1 (Meta)
- **WhatsApp Business Account ID:** from Step 1
- **Access token:** if reusing your system user token, paste it. Otherwise generate a clinic-specific token.
- **Google Maps URL:** from clinic's submission
- **Operating hours:** from clinic's submission
- **Languages:** comma-separated list (e.g., `en,hi,mr`)
- **Owner WhatsApp number:** for daily summaries (the clinic owner, not a doctor)
- Save

### Step 8 — Add Doctor(s)

Admin → **Doctors → Add Doctor** (one per doctor):

- **Clinic:** select the clinic from Step 7
- **Name:** as supplied
- **Specialty:** as supplied
- **WhatsApp number:** doctor's personal WhatsApp (for query forwarding)
- **Schedule:** working hours, days off
- Save

### Step 9 — Generate slots for the first month

Run:
```bash
python manage.py generate_monthly_slots --clinic <clinic-slug>
```

(or use the admin action if exposed in UI)

### Step 10 — Update message template names in clinic config

In the Clinic record, set:
- `template_reminder_day_before` = `reminder_day_before`
- `template_reminder_one_hour` = `reminder_one_hour`

(Names must match exactly what was submitted to Meta.)

---

## Phase 4 — Test before handoff

### Step 11 — Smoke test inbound

From any phone (not whitelisted, not the clinic's): send **"hi"** to the clinic's WhatsApp number → bot should reply with the welcome menu.

If no reply:
- Check Render logs for webhook errors
- Confirm Step 5 (webhook subscribed for this WABA)
- Confirm `access_token` and `phone_number_id` on the Clinic record are correct

### Step 12 — End-to-end booking test

1. Send "hi" → pick language → pick doctor → pick date → pick time → confirm
2. Verify: a Booking row appears in admin with the right details
3. Verify: confirmation message arrives in WhatsApp (within 5 sec)

### Step 13 — Test the day-before reminder template

From Django shell:
```python
from apps.bookings.tasks import send_reminders
send_reminders(clinic_id=<your-clinic-id>, type="day_before", dry_run=False)
```

Should send the `reminder_day_before` template to your test booking's patient number. Verify it arrives correctly formatted.

---

## Phase 5 — Handoff to clinic

### Step 14 — Hand over the artifacts

Send the clinic:

1. **Their bot's WhatsApp number** — they save it as `+91 XXXXX XXXXX`
2. **wa.me link**: `https://wa.me/91XXXXXXXXXX` — for sharing in posters, Instagram bio, Google My Business
3. **QR code** (generate at `qr.io` or similar pointing to the wa.me link) — for printing at reception, on bills, on visiting cards
4. **One-line patient script**: *"To book your appointment, WhatsApp us at +91 XXXXX XXXXX or scan this QR code. Available 24/7."*
5. **Their dashboard login** (if they want to see bookings live)

### Step 15 — First-week monitoring

For the first 7 days:
- Check daily that bookings flow through
- Make sure reminders fire on time (check Render logs)
- Check the doctor's daily summary arrives at end of day
- Be reachable on WhatsApp for the clinic owner's questions

---

## Per-clinic record sheet (keep one per clinic)

Save this in a spreadsheet — one row per clinic:

```
Clinic name:              ___________________
Phone number:             +91 _______________
Phone Number ID:          ___________________
WABA ID:                  ___________________
2SV PIN:                  ___________________  (store securely)
Display name:             ___________________
Date onboarded:           ___________________
Maps URL:                 ___________________
Owner WhatsApp:           +91 _______________
Languages:                ___________________
Templates approved:       day_before / one_hour
Last health check:        ___________________
```

---

## Common failures and fast fixes

| Symptom | Cause | Fix |
|---|---|---|
| OTP doesn't arrive | Clinic's phone has WhatsApp installed | Ask them to uninstall WhatsApp on that number first, then retry |
| Phone stuck "Pending" after OTP | Cloud API account not created | Run the `/register` curl in Step 2 |
| Display name rejected | Promo words, brand mismatch | Rename to the literal business name on their signage |
| Bot doesn't reply to "hi" | Webhook not subscribed for new WABA | Re-do Step 5 |
| Template stuck "In review" >48h | Meta queue backlog | Submit a support ticket via "Ask a question" on the template details page |
| Reminder doesn't send | Template name in clinic config doesn't match approved template | Verify exact spelling and lowercase |

---

## Scale path (not now — when you have 5+ clinics)

Manual onboarding above takes ~45 min active + 1 day waiting per clinic. At 5+ clinics this becomes painful.

**Solution: become a Tech Provider.**

1. Submit `whatsapp_business_management` permission to App Review (similar process to the `whatsapp_business_messaging` you already did).
2. After approval, integrate **Embedded Signup** into DocPing: clinics click "Connect WhatsApp" → log in with Facebook → grant permissions → Meta auto-creates the WABA, verifies the phone, issues the token.
3. Programmatic template creation: write templates once, push to all client WABAs via API.

Onboarding drops from 45 min → 5 min. Worth doing after clinic #3 or #4.
