#!/usr/bin/env bash
# Render build script — runs on every deploy.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Idempotent — only seeds if TEST_CLINIC_* env vars are set.
python manage.py seed_data || true

# Idempotent superuser. Creates the user only if it doesn't already exist, then
# populates landing-page contact fields from DJANGO_SUPERUSER_* env vars.
python manage.py shell <<'PYEOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()
bot_number = os.environ.get("DJANGO_SUPERUSER_BOT_NUMBER", "").strip()
contact_number = os.environ.get("DJANGO_SUPERUSER_CONTACT_NUMBER", "").strip()
contact_name = os.environ.get("DJANGO_SUPERUSER_CONTACT_NAME", "").strip()

if not username or not password:
    print("Superuser: skipped (DJANGO_SUPERUSER_USERNAME / _PASSWORD not set)")
else:
    user = User.objects.filter(username=username).first()
    if user is None:
        user = User.objects.create_superuser(
            username=username, email=email, password=password,
            bot_number=bot_number, contact_number=contact_number,
            contact_name=contact_name,
        )
        print(f"Superuser: created '{username}' with landing fields")
    else:
        # Backfill landing fields on an existing superuser if they're still blank
        changed = []
        for field, value in (("bot_number", bot_number),
                             ("contact_number", contact_number),
                             ("contact_name", contact_name)):
            if value and not getattr(user, field, ""):
                setattr(user, field, value)
                changed.append(field)
        if changed:
            user.save(update_fields=changed)
            print(f"Superuser: '{username}' already existed — backfilled {changed}")
        else:
            print(f"Superuser: '{username}' already exists, landing fields already set")
PYEOF

# Seed the full demo dataset (doctor + slots + patients + appointments).
# Idempotent — safe to run on every deploy. No-ops if TEST01 clinic doesn't exist yet.
python manage.py seed_demo || true
