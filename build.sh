#!/usr/bin/env bash
# Render build script — runs on every deploy.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Idempotent — only seeds if TEST_CLINIC_* env vars are set.
python manage.py seed_data || true
