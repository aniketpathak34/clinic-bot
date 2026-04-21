#!/usr/bin/env bash
# Render build script — runs on every deploy.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Idempotent — only seeds if TEST_CLINIC_* env vars are set.
python manage.py seed_data || true

# Idempotent superuser — creates one only if DJANGO_SUPERUSER_* env vars
# are set and no user with that username exists yet.
python manage.py shell <<'PYEOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "").strip()

if not username or not password:
    print("Superuser: skipped (DJANGO_SUPERUSER_USERNAME / _PASSWORD not set)")
elif User.objects.filter(username=username).exists():
    print(f"Superuser: '{username}' already exists")
else:
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"Superuser: created '{username}'")
PYEOF
