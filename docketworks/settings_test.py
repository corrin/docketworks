"""
Test settings — connects pytest as the per-instance test role.

Each tenant has a separate role (dw_<instance>_test) that owns the same-named
test database — no CREATEDB, no access to the app DB. This file just swaps
the DB credentials; conftest.py at the repo root handles schema reset and
migrations.
"""

import os

from .settings import *  # noqa: F401, F403
from .settings import DATABASES

TEST_DB_USER = os.environ["TEST_DB_USER"]
TEST_DB_PASSWORD = os.environ["TEST_DB_PASSWORD"]

DATABASES["default"]["USER"] = TEST_DB_USER
DATABASES["default"]["PASSWORD"] = TEST_DB_PASSWORD

# Run Celery tasks synchronously in tests — no broker required, no worker
# required, exceptions surface immediately at the call site.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
SOLO_CACHE = None

# Override the production "shared"=Redis cache with LocMem for tests. The
# eager-Celery test runner is single-process, so per-process LocMem has
# identical semantics to Redis here and avoids requiring a live Redis.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-default",
    },
    "shared": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-shared",
    },
}
