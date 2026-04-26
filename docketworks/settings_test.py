"""
Test settings — connects pytest as the per-instance test role.

Each tenant has a separate role (dw_<instance>_test) that owns only the
pre-provisioned test_dw_<instance> database — no CREATEDB, no access to
the app DB. This file just swaps the DB credentials; conftest.py at the
repo root handles schema reset and migrations.
"""

import os

from .settings import *  # noqa: F401, F403
from .settings import DATABASES

TEST_DB_USER = os.environ["TEST_DB_USER"]
TEST_DB_PASSWORD = os.environ["TEST_DB_PASSWORD"]

DATABASES["default"]["USER"] = TEST_DB_USER
DATABASES["default"]["PASSWORD"] = TEST_DB_PASSWORD
