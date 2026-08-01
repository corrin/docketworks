"""Test settings.

Local runs: values come from .env (loaded first, so it wins).
CI: no .env exists, so the setdefault fallbacks below match the CI service
containers (postgres/postgres, redis on 6379).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("APP_DOMAIN", "localhost")
os.environ.setdefault("DB_NAME", "docketworks_v2")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "postgres")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("FRONT_END_URL", "http://localhost:5173")
os.environ.setdefault(
    "DROPBOX_WORKFLOW_FOLDER",
    str(Path(__file__).resolve().parent.parent / ".test-dropbox-workflow"),
)

from config.settings import *  # noqa: E402, F403 -- env fallbacks must be set before settings import
