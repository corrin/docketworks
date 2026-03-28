"""
Test settings — uses dw_test user which has CREATEDB privilege.

The main DB user is tenant-isolated and cannot create databases.
This file overrides just the DB credentials for the test runner.
"""

import os

from .settings import *  # noqa: F401, F403
from .settings import DATABASES

TEST_DB_USER = os.environ["TEST_DB_USER"]
TEST_DB_PASSWORD = os.environ["TEST_DB_PASSWORD"]

DATABASES["default"]["USER"] = TEST_DB_USER
DATABASES["default"]["PASSWORD"] = TEST_DB_PASSWORD
