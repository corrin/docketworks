"""Django settings for Docketworks v2.

Settings grow per phase alongside their consumers; every required env var is
validated fail-fast at startup (no defaults that mask configuration problems).
"""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from redis.connection import parse_url as parse_redis_url

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

REQUIRED_ENV_VARS = [
    "SECRET_KEY",
    "JWT_SIGNING_KEY",
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
    "MEDIA_ROOT",
    "XERO_READONLY",
]


def validate_required_settings() -> None:
    """Fail fast at startup if any required environment variable is missing or empty."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    jwt_signing_key = os.environ["JWT_SIGNING_KEY"]
    if len(jwt_signing_key.encode()) < 32:
        raise RuntimeError("JWT_SIGNING_KEY must be at least 32 bytes for HS256")
    if jwt_signing_key == os.environ["SECRET_KEY"]:
        raise RuntimeError("JWT_SIGNING_KEY must be distinct from SECRET_KEY")


validate_required_settings()

SECRET_KEY = os.environ["SECRET_KEY"]
JWT_SIGNING_KEY = os.environ["JWT_SIGNING_KEY"]
DEBUG = os.environ["DEBUG"].lower() == "true"
APP_DOMAIN = os.environ["APP_DOMAIN"]

ALLOWED_HOSTS = [APP_DOMAIN, "localhost", "127.0.0.1"]

# No django.contrib.admin: administration happens through the app's own SPA.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.postgres",
    "django_celery_results",
    "django_eventstream",
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

# JWT signatures have their own deployment-managed key. Coupling them to
# Django's SECRET_KEY turns an unrelated framework-key rotation into a session
# invalidation; deliberate JWT key rotation remains the explicit logout-all
# control.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=90),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,  # Inert: token_blacklist is not installed.
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "VERIFYING_KEY": None,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ["ninja_jwt.tokens.AccessToken"],
    # Use the library's correctly spelled token-type claim setting.
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
    # Runs before the outer gzip middleware weakens the response ETag.
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

# Behind ngrok (dev/E2E) and nginx (UAT/prod) the app is reached over HTTPS on
# APP_DOMAIN while Django itself speaks plain HTTP. Without these it builds
# http:// absolute URLs, so an OAuth redirect_uri stops matching the one
# registered with the provider — which is exactly how the Xero callback breaks.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# Unsafe-method requests arriving through the tunnel carry the public origin.
CSRF_TRUSTED_ORIGINS = [f"https://{APP_DOMAIN}", f"http://{APP_DOMAIN}"]

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

# The value type admits nested dicts because settings_test.py assigns the
# TEST sub-dict (Django's documented shape); a str-only inference would force
# a type: ignore there.
DATABASES: dict[str, dict[str, str | dict[str, str]]] = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
    },
}


# Scratch alias used ONLY by the scrub-pipeline command
# (backport_data_backup on a production host): a
# sibling scrubbing database (dw_<client>_<env>_scrub) briefly holds a
# pg_restore'd copy that is anonymised in place before re-dumping. Optional
# rather than in REQUIRED_ENV_VARS — dev, CI and every non-producer instance
# have no scrub database, and requiring the variable everywhere would make
# each of them carry one for commands only an operator runs. Defined only
# when SCRUB_DB_NAME is set (an always-present alias with an empty NAME is a
# configuration lie, and the test runner would need a TEST MIRROR for it);
# the commands refuse with a clear message when the alias is absent. The
# suffix is validated here, at load, and ONLY here (ADR 0039, exclusivity):
# the alias cannot exist with a bad name, so a mispointed SCRUB_DB_NAME dies
# before any code can reach the commands' destructive DROP SCHEMA, and the
# pipeline and scrubber trust the alias they are handed.
def validate_scrub_db_name(name: str) -> None:
    """Refuse a scrub name that could point at a live database."""
    if not name.endswith("_scrub"):
        raise RuntimeError(
            f"SCRUB_DB_NAME ({name!r}) must end in '_scrub' — refusing to "
            "define a scrub database alias that could point at a live database."
        )


_scrub_db_name = os.environ.get("SCRUB_DB_NAME")
if _scrub_db_name:
    validate_scrub_db_name(_scrub_db_name)
    DATABASES["scrub"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _scrub_db_name,
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-nz"
TIME_ZONE = "Pacific/Auckland"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "media/"
# From env, not pinned to BASE_DIR: on a server BASE_DIR is the immutable,
# root-owned release directory — uploads (staff icons, company logos) must
# land in the instance's mutable mediafiles dir, which is also what nginx
# serves at /media/. A relative value resolves against BASE_DIR (the dev
# case); an absolute value stands alone.
MEDIA_ROOT = BASE_DIR / os.environ["MEDIA_ROOT"]

REDIS_URL = os.environ["REDIS_URL"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    },
    # Cross-process cache (gunicorn workers + celery): PDF-refresh dedup keys,
    # django-solo CompanyDefaults propagation uses a dedicated Redis database.
    "shared": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL.rsplit("/", 1)[0] + "/2",
        "KEY_PREFIX": APP_DOMAIN,
    },
}

# django-eventstream fans server-sent events across processes over Redis
# pub/sub. It builds BOTH a sync (eventstream.py) and an async (views.py)
# client from this dict, so it must hold plain connection keywords: a scheme
# that makes redis-py inject a connection_class hands the async client a
# synchronous class, which is why that is rejected at startup rather than at
# the first published event. settings_test.py deletes this setting entirely —
# the library switches to its in-process listener on its ABSENCE.
#
# redis-py ships py.typed but leaves parse_url itself unannotated. A local
# stub package for `redis` was the alternative, and it is worse: mypy_path
# stub packages cannot be marked partial, so `stubs/redis/__init__.pyi` would
# hide every real annotation the library already has.
EVENTSTREAM_REDIS: dict[str, object] = parse_redis_url(REDIS_URL)  # type: ignore[no-untyped-call]
if "connection_class" in EVENTSTREAM_REDIS:
    # Scheme, host and database, never the whole URL: REDIS_URL carries its
    # password in the userinfo, and this message goes to the journal and to
    # whatever ran the process. Naming the setting is what the operator needs;
    # echoing its value is how a credential ends up in a log an operator later
    # pastes into a ticket.
    _redis_parts = urlsplit(REDIS_URL)
    _redis_netloc = _redis_parts.hostname or ""
    if _redis_parts.port is not None:
        _redis_netloc = f"{_redis_netloc}:{_redis_parts.port}"
    raise RuntimeError(
        "REDIS_URL scheme is unusable for event fan-out: "
        f"{_redis_parts.scheme}://{_redis_netloc}{_redis_parts.path}"
    )

# Redis pub/sub is server-wide rather than scoped to a database index, and
# django-eventstream publishes every event on one hardcoded "events_channel",
# so two instances sharing a Redis server would deliver each other's events.
# The database name is the thing that tells those instances apart.
DATA_VERSIONS_CHANNEL = f"data-versions-{DATABASES['default']['NAME']}"

# django-solo caches CompanyDefaults.get_solo() across reads; routed onto
# "shared" makes edits propagate to every worker immediately.
SOLO_CACHE: str | None = "shared"  # settings_test overrides to None (no caching across tests)
SOLO_CACHE_TIMEOUT = 300

FRONT_END_URL = os.environ["FRONT_END_URL"]

# Process-scoped: suppress all Xero writes (reads/token refresh stay live).
# For E2E/test backends only — never set on a live server or celery worker
# serving real users. os.environ (not getenv): required var, crash if absent —
# and only the two exact spellings parse, because a typo silently enabling
# writes is the failure this flag exists to prevent.
_xero_readonly_raw = os.environ["XERO_READONLY"].lower()
if _xero_readonly_raw not in {"true", "false"}:
    raise ValueError(f"XERO_READONLY must be 'true' or 'false', got {_xero_readonly_raw!r}")
XERO_READONLY = _xero_readonly_raw == "true"

# Hardcoded, not env: these guard against pointing a non-production install
# at a production Xero tenant/app, and a guard that can be misconfigured
# away is no guard. Lists, one entry per onboarded client: the guards refuse
# only tenants/apps recorded here, so adding a client's production ids is a
# REQUIRED onboarding step (docs/client_onboarding.md, Phase 2b) — a new
# client's live organisation is unprotected until its entry merges.
PRODUCTION_XERO_TENANT_IDS = ["75e57cfd-302d-4f84-8734-8aae354e76a7"]
PRODUCTION_XERO_CLIENT_IDS = ["DB22E7201251487F83D98B130946DAC1"]
DROPBOX_WORKFLOW_FOLDER = os.environ["DROPBOX_WORKFLOW_FOLDER"]
PHONE_RECORDING_STORAGE_ROOT = os.environ["PHONE_RECORDING_STORAGE_ROOT"]

# Without an explicit LOGGING block Django installs a config that sends app
# loggers nowhere unless DEBUG is on, so every logger.warning in a service, task
# or data migration is silently discarded in production — the failure mode ADR
# 0038 exists to prevent. Everything goes to the console; systemd/journald and
# the E2E task panes capture it from there.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # Ours, at DEBUG when DEBUG is on: these carry the business context that
        # makes an error diagnosable rather than merely visible.
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        # django.db.backends at DEBUG logs every query; opt in deliberately, not
        # as a side effect of DEBUG=true.
        "django.db.backends": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = "django-db"
CELERY_RESULT_EXTENDED = True
# TaskResult rows are the only record of a beat firing (`last_run_at` on the
# scheduled-task endpoints derives from the newest one), and celery's default
# expiry is ONE day — shorter than the weekly scrape's interval, so its record
# was deleted mid-week by celery.backend_cleanup and the endpoint read null.
# 30 days keeps a month of execution history; cleanup still prunes beyond it.
CELERY_RESULT_EXPIRES = timedelta(days=30)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE
