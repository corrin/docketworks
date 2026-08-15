#!/usr/bin/env python
"""Dump the running Django configuration as sanitised JSON for diagnostics.

Reports versions, flags, proxy headers, database (plus live server version),
caches, event-stream fan-out, celery, logging levels and selected environment
variables. Secrets never appear: the DB password is dropped and every Redis
URL is reduced to scheme://host:port/db (REDIS_URL carries its password in
the userinfo).

Usage:
    uv run python -m scripts.ops.dump_settings
"""

import json
import logging
import os
import sys
from urllib.parse import urlsplit

import django

from scripts.bootstrap import setup_django

setup_django()

from django.conf import settings  # noqa: E402 -- Django must be configured first
from django.db import connection  # noqa: E402


def level(name: str) -> str:
    """Return the effective level name of the named logger."""
    return logging.getLevelName(logging.getLogger(name).getEffectiveLevel())


def sanitize_redis_url(url: str) -> str:
    """Reduce a Redis URL to scheme://host:port/db, dropping any userinfo."""
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme}://{netloc}{parts.path}"


def database_info() -> dict[str, object]:
    """The default database config (password dropped) plus live server version."""
    db = settings.DATABASES["default"]
    info: dict[str, object] = {
        "ENGINE": db["ENGINE"],
        "HOST": db["HOST"],
        "PORT": db["PORT"],
        "NAME": db["NAME"],
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            row = cursor.fetchone()
            info["server_version"] = row[0] if row else None
    except Exception as exc:  # noqa: BLE001 -- deliberate-swallow: an unreachable DB is a finding this diagnostic reports, not a reason to abort the dump
        info["server_version_error"] = str(exc)
    return info


def main() -> None:
    info: dict[str, object] = {}

    info["versions"] = {
        "python": sys.version.split()[0],
        "django": django.get_version(),
    }
    info["flags"] = {
        "DEBUG": settings.DEBUG,
        "XERO_READONLY": settings.XERO_READONLY,
        "APP_DOMAIN": settings.APP_DOMAIN,
    }

    info["proxy"] = {
        "USE_X_FORWARDED_HOST": settings.USE_X_FORWARDED_HOST,
        "USE_X_FORWARDED_PORT": settings.USE_X_FORWARDED_PORT,
        "SECURE_PROXY_SSL_HEADER": settings.SECURE_PROXY_SSL_HEADER,
        "CSRF_TRUSTED_ORIGINS": settings.CSRF_TRUSTED_ORIGINS,
    }

    info["files"] = {
        "STATIC_ROOT": str(settings.STATIC_ROOT),
        "MEDIA_ROOT": str(settings.MEDIA_ROOT),
    }

    info["logging"] = {
        "root_level": level(""),
        "apps_level": level("apps"),
        "django_db_backends_level": level("django.db.backends"),
    }

    info["database"] = database_info()

    info["caches"] = {
        "default": {
            "BACKEND": settings.CACHES["default"]["BACKEND"],
            "LOCATION": settings.CACHES["default"]["LOCATION"],
        },
        "shared": {
            "BACKEND": settings.CACHES["shared"]["BACKEND"],
            "LOCATION": sanitize_redis_url(settings.CACHES["shared"]["LOCATION"]),
            "KEY_PREFIX": settings.CACHES["shared"]["KEY_PREFIX"],
        },
    }
    info["solo_cache"] = {
        "SOLO_CACHE": settings.SOLO_CACHE,
        "SOLO_CACHE_TIMEOUT": settings.SOLO_CACHE_TIMEOUT,
    }

    # EVENTSTREAM_REDIS is parse_redis_url output and may include a password
    # key; report the topology and only whether a password is present.
    eventstream = settings.EVENTSTREAM_REDIS
    info["eventstream"] = {
        "host": eventstream.get("host"),
        "port": eventstream.get("port"),
        "db": eventstream.get("db"),
        "password_present": bool(eventstream.get("password")),
        "DATA_VERSIONS_CHANNEL": settings.DATA_VERSIONS_CHANNEL,
    }

    info["celery"] = {
        "BROKER_URL": sanitize_redis_url(settings.CELERY_BROKER_URL),
        "RESULT_BACKEND": settings.CELERY_RESULT_BACKEND,
        "RESULT_EXPIRES": str(settings.CELERY_RESULT_EXPIRES),
        "TASK_ACKS_LATE": settings.CELERY_TASK_ACKS_LATE,
        "WORKER_PREFETCH_MULTIPLIER": settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    }

    info["middleware"] = {"count": len(settings.MIDDLEWARE)}

    # DB endpoint env vars cross-check the settings above; the password and
    # REDIS_URL (userinfo credential) are deliberately absent.
    env_keys = [
        "DJANGO_SETTINGS_MODULE",
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_NAME",
    ]
    info["env"] = {key: os.getenv(key) for key in env_keys}

    print(json.dumps(info, indent=2, default=str))


if __name__ == "__main__":
    main()
