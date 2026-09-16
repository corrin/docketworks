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

# Model-free by design (see its docstring), so importing it here — before the
# app registry exists — is safe.
from apps.core.environment import required_flag, validate_scrub_db_name, validate_xero_fake_flag

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
    "SESSION_REPLAY_STORAGE_ROOT",
    "MEDIA_ROOT",
    "XERO_READONLY",
    "XERO_FAKE",
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
# Further hostnames this instance answers on (instance.sh --alias; comma-
# separated, usually empty). Everything that names the instance outbound —
# reset links, job links in Xero documents, the cache prefix — stays on
# APP_DOMAIN; an alias only admits requests. Present in every .env by the
# env-template contract but legitimately empty, so it is read here rather
# than listed in REQUIRED_ENV_VARS, which refuses an empty value.
APP_DOMAIN_ALIASES = [host for host in os.environ["APP_DOMAIN_ALIASES"].split(",") if host]

ALLOWED_HOSTS = [APP_DOMAIN, *APP_DOMAIN_ALIASES, "localhost", "127.0.0.1"]

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
    "apps.platform.integrations",
    "apps.platform.observability",
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
AUTHENTICATION_BACKENDS = ["apps.accounts.authentication.StaffEmailBackend"]

# Enforced wherever validate_password runs: the staff-admin write paths and the
# self-service change endpoint, all through _set_staff_password.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        # Fable: attributes named explicitly — the validator's defaults are
        # username/first_name/last_name/email, and Staff has no username or
        # email attribute, so the defaults would silently compare against
        # nothing for the address a person is most likely to reuse.
        "OPTIONS": {
            "user_attributes": [
                "office_email",
                "payroll_email",
                "first_name",
                "last_name",
                "preferred_name",
            ]
        },
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

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
    # Outside the auth gate so the logged status is the one the client saw,
    # including the gate's own 401s and redirects.
    "apps.core.middleware.AccessLoggingMiddleware",
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
CSRF_TRUSTED_ORIGINS = [
    f"https://{APP_DOMAIN}",
    f"http://{APP_DOMAIN}",
    *(f"https://{host}" for host in APP_DOMAIN_ALIASES),
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
# the commands refuse with a clear message when the alias is absent. Validating
# the suffix here is what makes the invariant true — the alias cannot exist
# with a bad name — and the rule itself lives in apps.core.environment, so the
# pipeline's own pre-DROP check calls it rather than restating it (ADR 0039).
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
    # django-solo CompanyDefaults propagation. Database 2 of the instance's own
    # Redis server (ADR 0065), beside the broker on the database REDIS_URL names.
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
# django-eventstream publishes every event on one hardcoded "events_channel".
# An instance's Redis server is its own (ADR 0065), but it still serves both
# the live database and the copy the verification window runs on (ADR 0064),
# so the database name is the thing that tells those two apart.
DATA_VERSIONS_CHANNEL = f"data-versions-{DATABASES['default']['NAME']}"

# Opus: Payroll runs get their OWN channel rather than an event on the one above,
# and the reason is authorisation rather than tidiness. That stream authenticates
# any staff member (CookieJWTAuth); this document carries names, hours and pay
# basis, so its view uses SuperuserCookieJWTAuth — sharing a channel would push
# other people's pay to every logged-in worker's open stream. Namespaced by
# database for the same reason as its sibling.
PAYROLL_RUNS_CHANNEL = f"payroll-runs-{DATABASES['default']['NAME']}"

# Fable: Xero sync progress gets its OWN channel for the same authorisation
# reason as payroll: data-versions authenticates any staff member, while sync
# progress is office-only (it carries AppError ids and per-entity operational
# detail, and its page's every action is office_auth). Namespaced by database
# like its siblings.
XERO_SYNC_CHANNEL = f"xero-sync-{DATABASES['default']['NAME']}"

# django-solo caches CompanyDefaults.get_solo() across reads; routed onto
# "shared" makes edits propagate to every worker immediately.
SOLO_CACHE: str | None = "shared"  # settings_test overrides to None (no caching across tests)
SOLO_CACHE_TIMEOUT = 300

FRONT_END_URL = os.environ["FRONT_END_URL"]

# Process-scoped: suppress all Xero writes (reads/token refresh stay live).
# The valve for a local process pointed at PRODUCTION data (ADR 0050) — never
# a test mode, and never set on a live server or celery worker serving real
# users.
XERO_READONLY = required_flag("XERO_READONLY")
# Process-scoped: answer every Xero call from the local fake (ADR 0060). Set
# by `run_e2e.sh --use-fake-xero` for the stack it starts, so an iteration run
# spends no Xero quota, and by `verify-instance.sh --e2e` for the copy of an
# instance it verifies (ADR 0064); the merge-gate run never sets it.
XERO_FAKE = required_flag("XERO_FAKE")
validate_xero_fake_flag(fake=XERO_FAKE, readonly=XERO_READONLY)

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
# Required, not v1's bare getenv: an unset root turned every chunk upload into
# a runtime TypeError deep in the storage layer instead of a boot failure.
SESSION_REPLAY_STORAGE_ROOT = os.environ["SESSION_REPLAY_STORAGE_ROOT"]

# Without an explicit LOGGING block Django installs a config that sends app
# loggers nowhere unless DEBUG is on, so every logger.warning in a service, task
# or data migration is silently discarded in production — the failure mode ADR
# 0038 exists to prevent. Everything goes to the console; systemd/journald and
# the E2E task panes capture it from there.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "suppress_traceback": {
            "()": "apps.core.logging_filters.SuppressTracebackFilter",
        },
    },
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
        # v1 gave this its own rotating access.log file. journald already
        # rotates, retains and greps, so a file handler here would only add a
        # second copy on disk for an operator to find and prune.
        "access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # Host-header probing is expected hostile traffic, not an application
        # fault. Django rejects it with 400 on its own; the record is kept as
        # the record of the probe, and only its traceback is dropped.
        "django.security.DisallowedHost": {
            "handlers": ["console"],
            "filters": ["suppress_traceback"],
            "level": "WARNING",
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
# The queue is named by the database, so a worker consumes only work queued
# for the database it is running on. The verification window (ADR 0064)
# restarts the worker on the scrub copy against the same Redis server; with
# one shared queue name it drained tasks the live instance had queued before
# the fence into the copy, and the teardown purge discarded the rest — on a
# production PVT that was lost work. No -Q on the worker unit: with
# task_queues unset the worker consumes exactly this queue, and a name baked
# into the unit would pin the live queue while the window changes the database.
CELERY_TASK_DEFAULT_QUEUE = DATABASES["default"]["NAME"]
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
