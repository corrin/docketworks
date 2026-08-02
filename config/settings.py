"""Django settings for Docketworks v2.

Settings grow per phase alongside their consumers; every required env var is
validated fail-fast at startup (no defaults that mask configuration problems).
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

REQUIRED_ENV_VARS = [
    "SECRET_KEY",
    "DEBUG",
    "APP_DOMAIN",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "REDIS_URL",
    "FRONT_END_URL",
    "DROPBOX_WORKFLOW_FOLDER",
    "PHONE_RECORDING_STORAGE_ROOT",
]


def validate_required_settings() -> None:
    """Fail fast at startup if any required environment variable is missing or empty."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


validate_required_settings()

SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.environ["DEBUG"].lower() == "true"
APP_DOMAIN = os.environ["APP_DOMAIN"]

ALLOWED_HOSTS = [APP_DOMAIN, "localhost", "127.0.0.1"]

# No django.contrib.admin: v1 runs without the Django admin (all administration
# happens through the app's own /admin SPA pages); v2 keeps that surface off.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.postgres",
    "django_celery_results",
    "simple_history",
    "solo",
    "apps.core",
    "apps.accounts",
    "apps.company",
    "apps.crm",
    "apps.job",
    "apps.timesheet",
    "apps.purchasing",
    "apps.quoting",
    "apps.accounting",
    "apps.operations",
    "apps.process",
    "apps.xero",
    "apps.ai",
    "apps.search",
    "apps.diagnostics",
]

AUTH_USER_MODEL = "accounts.Staff"

SITE_ID = 1

# ninja_jwt reads SIMPLE_JWT natively; the v1 key name and values are kept for
# simplicity. Session survival at cutover is NOT a requirement (users re-login;
# fresh SECRET_KEY is fine).
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=90),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,  # inert: no token_blacklist app (same as v1)
    "ALGORITHM": "HS256",
    "VERIFYING_KEY": None,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ["ninja_jwt.tokens.AccessToken"],
    # v1 had typo key TOKEN_TYPE_CLAIMS (silently ignored; default applied anyway)
    "TOKEN_TYPE_CLAIM": "token_type",
    # Cookie contract (read by apps.core.auth.jwt_cookie_config)
    "AUTH_COOKIE": "access_token",
    "AUTH_COOKIE_SECURE": not DEBUG,
    "AUTH_COOKIE_HTTP_ONLY": True,
    "AUTH_COOKIE_SAMESITE": "Lax",
    "AUTH_COOKIE_DOMAIN": None,
    "REFRESH_COOKIE": "refresh_token",
    "REFRESH_COOKIE_SECURE": not DEBUG,
    "REFRESH_COOKIE_HTTP_ONLY": True,
    "REFRESH_COOKIE_SAMESITE": "Lax",
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    # Runs on the response before the outer gzip middleware weakens ETag (v1 order).
    "apps.core.middleware.ResourceVersionMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-nz"
TIME_ZONE = "Pacific/Auckland"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

REDIS_URL = os.environ["REDIS_URL"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    },
    # Cross-process cache (gunicorn workers + celery): PDF-refresh dedup keys,
    # django-solo CompanyDefaults propagation. v1 used Redis db 2.
    "shared": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL.rsplit("/", 1)[0] + "/2",
        "KEY_PREFIX": APP_DOMAIN,
    },
}

# django-solo caches CompanyDefaults.get_solo() across reads; routed onto
# "shared" so edits propagate to every worker immediately (v1 behaviour).
SOLO_CACHE: str | None = "shared"  # settings_test overrides to None (no caching across tests)
SOLO_CACHE_TIMEOUT = 300

FRONT_END_URL = os.environ["FRONT_END_URL"]
DROPBOX_WORKFLOW_FOLDER = os.environ["DROPBOX_WORKFLOW_FOLDER"]
PHONE_RECORDING_STORAGE_ROOT = os.environ["PHONE_RECORDING_STORAGE_ROOT"]

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = "django-db"
CELERY_RESULT_EXTENDED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE
