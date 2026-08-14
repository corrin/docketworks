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
os.environ.setdefault("JWT_SIGNING_KEY", "test-only-jwt-signing-key-at-least-32-bytes")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("APP_DOMAIN", "localhost")
os.environ.setdefault("DB_NAME", "docketworks_v2")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "postgres")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
# Tests must never write to a Xero tenant — hard-set, not setdefault: an
# inherited XERO_READONLY=false from a dev shell would silently run the
# suite against the writable provider.
os.environ["XERO_READONLY"] = "true"
os.environ.setdefault("FRONT_END_URL", "http://localhost:5173")
os.environ.setdefault(
    "DROPBOX_WORKFLOW_FOLDER",
    str(Path(__file__).resolve().parent.parent / ".test-dropbox-workflow"),
)
os.environ.setdefault(
    "PHONE_RECORDING_STORAGE_ROOT",
    str(Path(__file__).resolve().parent.parent / ".test-phone-recordings"),
)
os.environ.setdefault("MEDIA_ROOT", "mediafiles")

from config.settings import *  # noqa: E402, F403 -- env fallbacks must be set before settings import

# The scrub alias exists only for the operator scrub-pipeline commands
# (backport_data_backup, export_dev_demo_dump). Left in place, the test
# runner would create and tear down a test database for it whenever a
# developer's .env carries SCRUB_DB_NAME.
DATABASES.pop("scrub", None)  # noqa: F405 -- star-imported from config.settings above

# On a server instance, pytest connects as the per-tenant test role
# (dw_<client>_<env>_test, provisioned by scripts/server/instance.sh with
# CREATEDB) so test runs never hold the app role's credentials, and the test
# database is the role's own name — matching what instance.sh destroy drops —
# rather than Django's default test_<DB_NAME>. Checked for truthiness, not
# presence: a dev .env copied from .env.example carries the variable blank
# (dev checkouts have no per-tenant role and keep connecting as DB_USER).
_test_db_user = os.environ.get("TEST_DB_USER")
if _test_db_user:
    DATABASES["default"]["USER"] = _test_db_user  # noqa: F405
    DATABASES["default"]["PASSWORD"] = os.environ["TEST_DB_PASSWORD"]  # noqa: F405
    DATABASES["default"]["TEST"] = {"NAME": _test_db_user}  # noqa: F405

# Tasks execute inline in tests; real job task bodies landed
# in Phase 3b-3. Dispatch-semantics tests still mock .apply_async and use the
# on_commit capture pattern (apps/job/tests/test_job_tasks.py) — pytest-django
# wraps tests in transactions, so on_commit callbacks only run when captured.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Tests run everything in-process with no Redis dependency,
# and solo must not cache across tests.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "shared": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}
SOLO_CACHE = None

# django-eventstream picks its multiprocess Redis listener on the mere
# PRESENCE of this setting (hasattr checks in its eventstream.py and views.py),
# so the suite deletes it rather than blanking it: one process, one in-memory
# listener, no Redis.
del EVENTSTREAM_REDIS  # noqa: F821 -- star-imported from config.settings above
