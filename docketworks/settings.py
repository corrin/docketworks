import logging
import os
import subprocess
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Import scopes from constants to ensure consistency
from apps.workflow.api.xero.constants import XERO_SCOPES as DEFAULT_XERO_SCOPES_LIST

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=False)

# Git SHA of the running process. Served by /api/build-id/ so the frontend can
# detect when a deploy has happened and force a reload. Captured at import
# time: gunicorn restart on deploy re-imports and picks up the new SHA.
BUILD_ID = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=BASE_DIR,
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def validate_required_settings() -> None:
    """Validate that all required settings are properly configured."""
    # Define core required environment variables that must be set
    required_env_vars = [
        # Django Core
        "SECRET_KEY",
        "DEBUG",
        "DEBUG_PAYLOAD",
        "SKIP_VERSION_CHECK",
        "DJANGO_ENV",
        "ALLOWED_HOSTS",
        "DJANGO_SITE_DOMAIN",
        # Database
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        # File Storage
        "DROPBOX_WORKFLOW_FOLDER",
        # Xero Integration
        "XERO_CLIENT_ID",
        "XERO_CLIENT_SECRET",
        "XERO_REDIRECT_URI",
        "XERO_DEFAULT_USER_ID",
        "XERO_SYNC_PROJECTS",
        "XERO_WEBHOOK_KEY",
        # Email
        "EMAIL_HOST",
        "EMAIL_PORT",
        "EMAIL_USE_TLS",
        "EMAIL_HOST_USER",
        "EMAIL_HOST_PASSWORD",
        "DEFAULT_FROM_EMAIL",
        # Authentication
        "ENABLE_JWT_AUTH",
        # Frontend Integration
        "FRONT_END_URL",
    ]

    # Check which variables are missing or empty
    missing_vars = []
    for var_name in required_env_vars:
        value = os.getenv(var_name)
        if not value:
            missing_vars.append(var_name)

    if missing_vars:
        error_msg = f"Missing {len(missing_vars)} required environment variable(s):\n"
        for var in missing_vars:
            error_msg += f"  • {var}\n"

        error_msg += "Add the missing variables to your .env file\n"

        raise ImproperlyConfigured(error_msg)


# Validate required settings BEFORE accessing any environment variables
validate_required_settings()

# Load DEBUG from environment - should be False in production
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Enable detailed payload logging for debugging
DEBUG_PAYLOAD = os.getenv("DEBUG_PAYLOAD").lower() == "true"

# Disable the build-id / version-check feature. When True, /api/build-id/
# returns an empty build_id sentinel and the frontend skips its reload check.
SKIP_VERSION_CHECK = os.getenv("SKIP_VERSION_CHECK").lower() == "true"

# Job delta soft fail setting - controls whether checksum mismatches are logged but not raised
JOB_DELTA_SOFT_FAIL = os.getenv("JOB_DELTA_SOFT_FAIL", "True").strip() == "True"


# =======================
# Cookie Configuration
# =======================
# Control scheduler registration - only register jobs when explicitly enabled
RUN_SCHEDULER = os.getenv("DJANGO_RUN_SCHEDULER")

# Detect production-like environment (for UAT/production)
# This matches the original settings/__init__.py logic
DJANGO_ENV = os.getenv("DJANGO_ENV")
if not DJANGO_ENV:
    # Default to development if DJANGO_ENV is not set
    DJANGO_ENV = "INVALID SYSTEM DETECTED - KILL CLAUDE CODE"
PRODUCTION_LIKE = DJANGO_ENV == "production_like"

# Load SECRET_KEY from environment - critical security requirement
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY environment variable must be set. "
        "Generate one using: from django.core.management.utils import "
        "get_random_secret_key; print(get_random_secret_key())"
    )

# Load ALLOWED_HOSTS from environment variables
allowed_hosts_env = os.getenv("ALLOWED_HOSTS", "")
if allowed_hosts_env:
    ALLOWED_HOSTS = [
        host.strip() for host in allowed_hosts_env.split(",") if host.strip()
    ]
else:
    # Fallback for development
    ALLOWED_HOSTS = [
        "127.0.0.1",
        "localhost",
    ]

AUTH_USER_MODEL = "accounts.Staff"

# Application definition
INSTALLED_APPS = [
    "django_apscheduler",
    "solo",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "django.contrib.humanize",
    "rest_framework",
    "simple_history",
    "apps.workflow.apps.WorkflowConfig",
    "apps.accounting.apps.AccountingConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.timesheet.apps.TimesheetConfig",
    "apps.job.apps.JobConfig",
    "apps.quoting.apps.QuotingConfig",
    "apps.client.apps.ClientConfig",
    "apps.purchasing.apps.PurchasingConfig",
    "apps.process.apps.ProcessConfig",
    "apps.operations.apps.OperationsConfig",
    "channels",
    "mcp_server",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.workflow.middleware.DisallowedHostMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.workflow.middleware.FrontendRedirectMiddleware",
    "apps.workflow.middleware.AccessLoggingMiddleware",
    "apps.workflow.middleware.LoginRequiredMiddleware",
    "apps.workflow.middleware.E2ECacheBypassMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

# CSRF settings - Load from environment variables
csrf_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
csrf_trusted_origins = []

if csrf_origins_env:
    # Convert CORS origins to CSRF trusted origins (add https:// variants)
    for origin in csrf_origins_env.split(","):
        origin = origin.strip()
        if origin:
            csrf_trusted_origins.append(origin)
            # Add https variant if it's http
            if origin.startswith("http://"):
                https_variant = origin.replace("http://", "https://")
                csrf_trusted_origins.append(https_variant)

# Add ngrok domain if available
CSRF_TRUSTED_ORIGINS = (
    csrf_trusted_origins
    if csrf_trusted_origins
    else [
        "http://localhost",
        "http://127.0.0.1",
    ]
)

# JWT/authentication settings
ENABLE_JWT_AUTH = os.getenv("ENABLE_JWT_AUTH", "True").lower() == "true"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.workflow.authentication.JWTAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "COERCE_DECIMAL_TO_STRING": False,
    "EXCEPTION_HANDLER": "apps.workflow.exception_handlers.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=90),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "VERIFYING_KEY": None,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIMS": "token_type",
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

# Session cookie settings
SESSION_COOKIE_SECURE = not DEBUG  # Allow non-HTTPS session cookies in development
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG  # Allow non-HTTPS CSRF cookies in development
CSRF_COOKIE_HTTPONLY = False  # CSRF cookies need to be accessible to JS

FRONT_END_URL = os.getenv("FRONT_END_URL", "")
LOGIN_URL = FRONT_END_URL.rstrip("/") + "/login"
LOGOUT_URL = "accounts:api_logout"
LOGIN_REDIRECT_URL = FRONT_END_URL
LOGIN_EXEMPT_URLS = [
    "accounts:api_logout",
    "accounts:token_obtain_pair",
    "accounts:token_refresh",
    "accounts:token_verify",
    "build_id",
]

# API path prefixes - single source of truth for middlewares
# These paths bypass browser redirect and use DRF/JWT authentication
API_PATH_PREFIXES = ["/api/"]

# For OpenAPI schema generator
SPECTACULAR_SETTINGS = {
    "TITLE": "DocketWorks API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Split request/response schemas so code generators don't require readOnly fields
    # on request bodies. This creates e.g. ClientContact (response) and
    # ClientContactRequest (request) schemas automatically.
    "COMPONENT_SPLIT_REQUEST": True,
    # ENUM_NAME_OVERRIDES: key = desired schema name, value = choices tuple.
    # Resolves collisions where multiple models share a field name (e.g. "kind",
    # "status") but have different choice sets.
    "ENUM_NAME_OVERRIDES": {
        "AllocationTypeEnum": (
            ("stock", "Stock"),
            ("job", "Job"),
        ),
        "CostLineKindEnum": (
            ("time", "Time"),
            ("material", "Material"),
            ("adjust", "Adjustment"),
        ),
        "CostSetKindEnum": (
            ("estimate", "Estimate"),
            ("quote", "Quote"),
            ("actual", "Actual"),
        ),
        "InvoiceStatusEnum": (
            ("DRAFT", "Draft"),
            ("SUBMITTED", "Submitted"),
            ("AUTHORISED", "Authorised"),
            ("DELETED", "Deleted"),
            ("VOIDED", "Voided"),
            ("PAID", "Paid"),
        ),
        "QuoteStatusEnum": (
            ("DRAFT", "Draft"),
            ("SENT", "Sent"),
            ("DECLINED", "Declined"),
            ("ACCEPTED", "Accepted"),
            ("INVOICED", "Invoiced"),
            ("DELETED", "Deleted"),
        ),
        "JobStatusEnum": (
            ("draft", "Draft"),
            ("awaiting_approval", "Awaiting Approval"),
            ("approved", "Approved"),
            ("in_progress", "In Progress"),
            ("unusual", "Unusual"),
            ("recently_completed", "Recently Completed"),
            ("special", "Special"),
            ("archived", "Archived"),
        ),
        "ProcedureStatusEnum": (
            ("draft", "Draft"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("archived", "Archived"),
        ),
        "FormStatusEnum": (
            ("active", "Active"),
            ("archived", "Archived"),
        ),
        "ProcedureDocumentTypeEnum": (
            ("procedure", "Procedure"),
            ("reference", "Reference"),
        ),
        "FormDocumentTypeEnum": (
            ("form", "Form"),
            ("register", "Register"),
        ),
    },
}

ROOT_URLCONF = "docketworks.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            os.path.join(BASE_DIR, "apps/workflow/templates"),
            os.path.join(BASE_DIR, "apps/accounts/templates"),
            os.path.join(BASE_DIR, "apps/timesheet/templates"),
            os.path.join(BASE_DIR, "apps/job/templates"),
            os.path.join(BASE_DIR, "apps/client/templates"),
            os.path.join(BASE_DIR, "apps/purchasing/templates"),
            os.path.join(BASE_DIR, "apps/accounting/templates"),
            os.path.join(BASE_DIR, "apps/quoting/templates"),
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.workflow.context_processors.debug_mode",
            ],
        },
    },
]

WSGI_APPLICATION = "docketworks.wsgi.application"
ASGI_APPLICATION = "docketworks.asgi.application"

# Django Channels configuration
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                (
                    os.getenv("REDIS_HOST", "127.0.0.1"),
                    int(os.getenv("REDIS_PORT", 6379)),
                )
            ],
        },
    },
}

# MCP Configuration
DJANGO_MCP_AUTHENTICATION_CLASSES = [
    "rest_framework.authentication.SessionAuthentication",
]

# Database
DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", ""),
    },
    # Second DB alias used ONLY by manage.py backport_data_backup on prod.
    # Points at a sibling scrubbing DB (dw_<client>_scrub) that holds a
    # temporary copy of prod restored via pg_restore. The db_scrubber service
    # anonymises in place here before re-dumping. Name MUST end in "_scrub"
    # — hard-checked by db_scrubber to prevent accidental scrubbing of prod.
    "scrub": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("SCRUB_DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", ""),
    },
}

# Test runner configuration
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
        "OPTIONS": {
            "user_attributes": ["email", "first_name", "last_name", "preferred_name"],
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-nz"
TIME_ZONE = "Pacific/Auckland"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Media files (user uploads)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Log directory — defaults to BASE_DIR/logs, overridable via LOG_DIR env var
# (allows per-instance log directories in shared-codebase UAT deployments)
LOG_DIR = os.getenv("LOG_DIR", os.path.join(BASE_DIR, "logs"))

# Logging configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name}:{lineno} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "access": {
            "format": "{message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "sql_file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "debug_sql.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "xero_file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "xero_integration.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "purchase_file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "purchase_debug.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "app_file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "application.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "scheduler_file": {
            "level": "INFO",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "scheduler.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "ai_extraction_file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "ai_extraction.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
        },
        "ai_chat_file": {
            "level": "DEBUG",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "ai_chat.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "verbose",
        },
        "access_file": {
            "level": "INFO",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "access.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "access",
        },
        "mail_admins": {
            "level": "ERROR",
            "class": "django.utils.log.AdminEmailHandler",
            "include_html": True,
        },
        "auth_file": {
            "level": "INFO",
            "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "auth.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django.db.backends": {
            "handlers": ["sql_file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["app_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["access_file"],
            "level": "INFO",
            "propagate": False,
        },
        "xero": {
            "handlers": ["xero_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "xero_python": {
            "handlers": ["xero_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "workflow": {
            "handlers": ["app_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "apps.purchasing.views": {
            "handlers": ["purchase_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "django_apscheduler": {
            "handlers": ["console", "scheduler_file"],
            "level": "INFO",
            "propagate": False,
        },
        "access": {
            "handlers": ["access_file"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.quoting.services.ai_price_extraction": {
            "handlers": ["ai_extraction_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "apps.quoting.services.providers": {
            "handlers": ["ai_extraction_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "apps.job.services.gemini_chat_service": {
            "handlers": ["ai_chat_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "apps.job.services.mcp_chat_service": {
            "handlers": ["ai_chat_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "apps.job.views.job_quote_chat_api": {
            "handlers": ["ai_chat_file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "mcp_server": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "LiteLLM": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "litellm": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "httpx": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "httpcore": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps.accounts": {
            "handlers": ["auth_file"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.workflow.authentication": {
            "handlers": ["auth_file"],
            "level": "INFO",
            "propagate": False,
        },
        "auth": {
            "handlers": ["auth_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console", "app_file"],
        "level": "DEBUG",
    },
}

# Custom settings
ACCOUNTING_BACKEND = os.getenv("ACCOUNTING_BACKEND", "xero")
XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID", "")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET", "")
XERO_REDIRECT_URI = os.getenv("XERO_REDIRECT_URI", "")
XERO_DEFAULT_USER_ID = os.getenv("XERO_DEFAULT_USER_ID", "")
XERO_WEBHOOK_KEY = os.getenv("XERO_WEBHOOK_KEY", "")
XERO_SYNC_PROJECTS = os.getenv("XERO_SYNC_PROJECTS", "False").lower() == "true"

DEFAULT_XERO_SCOPES = " ".join(DEFAULT_XERO_SCOPES_LIST)
XERO_SCOPES = os.getenv("XERO_SCOPES", DEFAULT_XERO_SCOPES).split()

# Hardcoded production Xero tenant ID
PRODUCTION_XERO_TENANT_ID = "75e57cfd-302d-4f84-8734-8aae354e76a7"

# Hardcoded production machine ID
PRODUCTION_MACHINE_ID = "19d6339c35f7416b9f41d9a35dba6111"

DROPBOX_WORKFLOW_FOLDER = os.getenv("DROPBOX_WORKFLOW_FOLDER")

SITE_ID = 1

# File upload limits (20MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# EMAIL CONFIGURATION
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL")

# Admin email notifications for errors
_admin_email = os.getenv("DJANGO_ADMINS")
ADMINS = [("Admin", _admin_email)] if _admin_email else []

# Email BCC list
EMAIL_BCC_ENV = os.getenv("EMAIL_BCC")
EMAIL_BCC = (
    [email.strip() for email in EMAIL_BCC_ENV.split(",") if email.strip()]
    if EMAIL_BCC_ENV
    else []
)

# CACHE CONFIGURATION
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

# django-solo: cache SingletonModel.get_solo() results (e.g. CompanyDefaults).
# LocMemCache is per-worker, so admin edits to CompanyDefaults take up to
# SOLO_CACHE_TIMEOUT seconds to propagate across all gunicorn workers.
SOLO_CACHE = "default"
SOLO_CACHE_TIMEOUT = 300

# Password reset timeout
PASSWORD_RESET_TIMEOUT = 86400  # 24 hours in seconds


# Settings validation has been moved to the top of the file

# ==========================================
# PRODUCTION-LIKE SETTINGS OVERRIDES
# ==========================================
# These settings are applied when PRODUCTION_LIKE=True is set in environment
# Used for UAT, staging, and production environments

if PRODUCTION_LIKE:
    # Override media path from environment if provided
    MEDIA_ROOT = os.getenv("MEDIA_ROOT", MEDIA_ROOT)

    # SECURITY CONFIGURATIONS
    # Enable secure cookies and headers
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Security headers
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

    # Proxy/Load Balancer Configuration for UAT/Production
    # Trust the proxy headers to determine HTTPS status
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    USE_X_FORWARDED_PORT = True

    # CACHE CONFIGURATION
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake",
        }
    }

    # JWT Configuration for production - secure cookies
    SIMPLE_JWT.update(
        {
            "AUTH_COOKIE_SECURE": True,  # Require HTTPS for auth cookies in production
            "AUTH_COOKIE_HTTP_ONLY": True,  # httpOnly for security
            "AUTH_COOKIE_SAMESITE": "Lax",
            "REFRESH_COOKIE": "refresh_token",
            "REFRESH_COOKIE_SECURE": True,  # Require HTTPS for refresh cookies
            "REFRESH_COOKIE_HTTP_ONLY": True,
            "REFRESH_COOKIE_SAMESITE": "Lax",
        }
    )

    # Password reset timeout
    PASSWORD_RESET_TIMEOUT = 86400  # 24 hours in seconds

    # Site configuration for production
    def configure_site_for_environment():
        try:
            from django.apps import apps
            from django.db import ProgrammingError

            if apps.is_installed("django.contrib.sites"):
                Site = apps.get_model("sites", "Site")
                current_domain = os.getenv("DJANGO_SITE_DOMAIN")
                current_name = "DocketWorks"

                try:
                    site = Site.objects.get(pk=SITE_ID)
                    if site.domain != current_domain or site.name != current_name:
                        site.domain = current_domain
                        site.name = current_name
                        site.save()
                except Site.DoesNotExist:
                    Site.objects.create(
                        pk=SITE_ID, domain=current_domain, name=current_name
                    )
        except ProgrammingError as e:
            # Database tables don't exist yet (pre-migration) - unusual but possible
            logger = logging.getLogger(__name__)
            logger.warning(f"Site configuration skipped - database not ready: {e}")
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error configuring the site: {e}")

    # Configure site once on first request (DB may not be ready at import time)
    from django.core.signals import request_started

    def _configure_site_once(**kwargs):
        configure_site_for_environment()
        request_started.disconnect(_configure_site_once, dispatch_uid="configure_site")

    request_started.connect(
        _configure_site_once,
        weak=False,
        dispatch_uid="configure_site",
    )
