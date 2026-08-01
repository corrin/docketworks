"""Test settings: real settings with env supplied so tests never depend on a local .env."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("APP_DOMAIN", "localhost")
os.environ.setdefault("DB_NAME", "docketworks_v2_test")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "postgres")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")

from config.settings import *  # noqa: F403
