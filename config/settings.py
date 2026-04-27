"""
Django settings for WhatsApp Clinic Bot.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-dev-key-change-in-production')
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

_hosts = os.getenv('ALLOWED_HOSTS', '').strip()
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(',') if h.strip()] if _hosts else ['*']

# Render sets RENDER_EXTERNAL_HOSTNAME automatically; append it so the webhook resolves.
_render_host = os.getenv('RENDER_EXTERNAL_HOSTNAME')
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_render_host)

CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if origin.strip()
]
if _render_host:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")

# Application definition
INSTALLED_APPS = [
    # Custom user app must be registered before django.contrib.auth/admin
    # so AUTH_USER_MODEL resolves cleanly.
    'apps.accounts',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party — admin UI for editing/triggering Celery periodic tasks
    'django_celery_beat',
    # Project apps
    'apps.clinic',
    'apps.conversations',
    'apps.whatsapp',
    'apps.notifications',
    'apps.marketing',
]

AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database — SQLite for dev, PostgreSQL when DATABASE_URL is set (Render).
_database_url = os.getenv('DATABASE_URL', '').strip()
if _database_url:
    import dj_database_url
    DATABASES = {
        'default': dj_database_url.parse(_database_url, conn_max_age=600, ssl_require=True),
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# User-uploaded files (demo videos, posters).
# NOTE: Render free tier has an ephemeral filesystem — uploaded files are wiped
# on every redeploy. Prefer YouTube/Vimeo URLs on DemoVideo.embed_url in prod.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# WhiteNoise by default serves only STATIC_ROOT. Point it at MEDIA_ROOT too so
# uploaded videos/posters are streamed directly by WhiteNoise (faster + correct
# Content-Type headers) rather than Django's dev static() helper.
WHITENOISE_ROOT = MEDIA_ROOT

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Groq (Llama 3.1)
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')

# Google Places API (lead generation)
GOOGLE_PLACES_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY', '')

# Meta WhatsApp Cloud API — per-clinic credentials live on the Clinic model.
# These are fallbacks / defaults for admin tasks or when a clinic row doesn't
# override the access token.
META_ACCESS_TOKEN = os.getenv('META_ACCESS_TOKEN', '')
META_DEFAULT_PHONE_NUMBER_ID = os.getenv('META_DEFAULT_PHONE_NUMBER_ID', '')
META_GRAPH_API_VERSION = os.getenv('META_GRAPH_API_VERSION', 'v21.0')

WHATSAPP_VERIFY_TOKEN = os.getenv('WHATSAPP_VERIFY_TOKEN', 'clinic-bot-verify')
WHATSAPP_SERVICE_CLASS = os.getenv(
    'WHATSAPP_SERVICE_CLASS',
    'apps.whatsapp.meta_service.MetaWhatsAppService',
)
# For local dev without Meta credentials:
# WHATSAPP_SERVICE_CLASS=apps.whatsapp.mock_service.MockWhatsAppService

# Automated Calls (Twilio — mock for dev)
CALL_SERVICE_CLASS = os.getenv(
    'CALL_SERVICE_CLASS',
    'apps.notifications.call_service.MockCallService'
)
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '')
CALL_CALLBACK_URL = os.getenv('CALL_CALLBACK_URL', 'http://localhost:8000')

# Celery
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = 'Asia/Kolkata'

# Periodic tasks live in the DB so admins can edit/disable them at
# /admin/django_celery_beat/periodictask/  (instead of a code change).
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
