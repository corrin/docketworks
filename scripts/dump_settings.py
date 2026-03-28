#!/usr/bin/env python
"""
Dump current Django settings as JSON for diagnostics.

Outputs sanitized configuration including versions, database, cache,
channels, security headers, and selected environment variables.
Passwords and secrets are excluded.

Usage:
    python scripts/dump_settings.py
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)


def level(name):
    return logging.getLevelName(logging.getLogger(name).getEffectiveLevel())


def main():
    info = {}

    # Versions and flags

    info["versions"] = {
        "python": sys.version.split()[0],
        "django": django.get_version(),
    }
    info["flags"] = {
        "DEBUG": settings.DEBUG,
        "PRODUCTION_LIKE": getattr(settings, "PRODUCTION_LIKE", False),
    }

    # Proxy/security headers

    info["proxy"] = {
        "USE_X_FORWARDED_HOST": getattr(settings, "USE_X_FORWARDED_HOST", None),
        "USE_X_FORWARDED_PORT": getattr(settings, "USE_X_FORWARDED_PORT", None),
        "SECURE_PROXY_SSL_HEADER": getattr(settings, "SECURE_PROXY_SSL_HEADER", None),
    }
    info["security"] = {
        "SECURE_HSTS_SECONDS": getattr(settings, "SECURE_HSTS_SECONDS", 0),
        "SESSION_COOKIE_SECURE": getattr(settings, "SESSION_COOKIE_SECURE", None),
        "CSRF_COOKIE_SECURE": getattr(settings, "CSRF_COOKIE_SECURE", None),
    }
    info["static"] = {
        "STATICFILES_STORAGE": getattr(settings, "STATICFILES_STORAGE", None)
    }

    # Logging

    info["logging"] = {
        "root_level": level(""),
        "django_db_backends_level": level("django.db.backends"),
    }

    # Database (sanitized) + server version

    db = settings.DATABASES.get("default", {}).copy()
    if db:
        db.pop("PASSWORD", None)
        info["database"] = {
            "ENGINE": db.get("ENGINE"),
            "HOST": db.get("HOST"),
            "PORT": db.get("PORT"),
            "NAME": db.get("NAME"),
            "CONN_MAX_AGE": db.get("CONN_MAX_AGE", 0),
            "OPTIONS": db.get("OPTIONS"),
        }
        try:
            with connection.cursor() as c:
                c.execute("SELECT VERSION()")
                info["database"]["server_version"] = c.fetchone()[0]
        except Exception as e:
            info["database"]["server_version_error"] = str(e)

    # Cache and Channels/Redis

    info["cache"] = {
        "BACKEND": settings.CACHES["default"]["BACKEND"],
        "LOCATION": settings.CACHES["default"].get("LOCATION"),
    }
    cl = getattr(settings, "CHANNEL_LAYERS", None)
    info["channels"] = (
        {
            "BACKEND": cl["default"]["BACKEND"],
            "hosts": cl["default"]["CONFIG"].get("hosts"),
        }
        if cl
        else None
    )

    # Debug toolbar presence

    info["apps"] = {"debug_toolbar": "debug_toolbar" in settings.INSTALLED_APPS}
    info["middleware"] = {
        "debug_toolbar": any("debug_toolbar" in mw for mw in settings.MIDDLEWARE),
        "count": len(settings.MIDDLEWARE),
    }

    # Selected env vars (sanitized)

    env_keys = [
        "WEB_CONCURRENCY",
        "GUNICORN_CMD_ARGS",
        "DJANGO_SETTINGS_MODULE",
        "DB_HOST",
        "DB_PORT",
        "MYSQL_DB_USER",
        "MYSQL_DATABASE",
        "REDIS_HOST",
        "REDIS_PORT",
    ]
    info["env"] = {k: os.getenv(k) for k in env_keys}

    output = json.dumps(info, indent=2, default=str)
    logger.info("Settings dump:\n%s", output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
