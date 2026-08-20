"""Test settings.

Local runs: values come from .env (loaded first, so it wins).
CI: no .env exists, so the setdefault fallbacks below match the CI service
containers (postgres/postgres, redis on 6379).
"""

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

# Model-free by design (its docstring says why), so importing it before the
# settings star-import is safe.
from apps.core.environment import database_class

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
# Opus: XERO_READONLY is a production hotfix valve — it exists so an operator running
# a local process against PRODUCTION cannot emit real side effects (ADR 0050).
# It is NOT a test mechanism, and this file used to hard-set it to "true",
# which silently ran the entire suite against the write-suppressing provider
# and would have done the same to the integration suite — a green run that
# proved nothing.
#
# What keeps unit tests off the network is the autouse guard in the root
# conftest, which fails a test that reaches a vendor instead of quietly faking
# it. Integration tests (ADR 0050) deliberately DO reach the dev tenant, which
# exists for exactly that. A test of the valve itself sets it locally with
# override_settings.
os.environ.setdefault("XERO_READONLY", "false")
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

# The scrub alias exists only for the operator scrub-pipeline command
# (backport_data_backup). Left in place, the test
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
else:
    # Dev checkouts: derive the test database name from the checkout path,
    # so every worktree gets its own test_<db>_<slug> automatically.
    # Concurrent agent sessions in different worktrees repeatedly clobbered
    # the shared test_<DB_NAME> mid-run; the rejected alternative — each
    # session remembering to export its own DB_NAME — failed every time it
    # relied on memory. The slug is a path hash, so it is deterministic and
    # --reuse-db keeps working per checkout. Two simultaneous full runs in
    # the SAME checkout still share a name; xdist workers already suffix
    # _gwN, so that only bites two independent `pytest` invocations in one
    # directory at once.
    _checkout = Path(__file__).resolve().parent.parent
    _slug = hashlib.sha256(str(_checkout).encode()).hexdigest()[:8]
    DATABASES["default"]["TEST"] = {  # noqa: F405
        "NAME": f"test_{os.environ['DB_NAME']}_{_slug}"
    }

# A checkout pointed at a production database must not run the suite unless
# it is a provisioned instance, where the per-tenant test role above keeps
# the app credentials out of the run entirely. This is the careful-bypass
# lever: provisioning the role (instance.sh) is the deliberate act that
# permits tests near production; an ad-hoc .env aimed at prod is refused.
if database_class(str(DATABASES["default"]["NAME"])) == "prod" and not _test_db_user:  # noqa: F405
    raise RuntimeError(
        "DB_NAME ends in _prod and no per-tenant TEST_DB_USER is configured: "
        "refusing to run tests with production app credentials. Provision the "
        "instance test role (scripts/server/instance.sh) or point .env at a "
        "non-production database."
    )

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
