"""
Shared test utilities and base classes for the docketworks project.

All test classes that need database models should inherit from BaseTestCase
to ensure required fixtures are loaded.
"""

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APITestCase

if TYPE_CHECKING:
    from apps.accounts.models import Staff


def _ensure_test_media_files():
    """Install fixture-referenced media files into the active test MEDIA_ROOT."""
    if not settings.MEDIA_ROOT:
        raise RuntimeError("MEDIA_ROOT must be configured for DB-backed tests")

    repo_root = Path(__file__).resolve().parents[1]
    source_dir = repo_root / "mediafiles" / "app_images"
    dest_dir = Path(settings.MEDIA_ROOT) / "app_images"
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("docketworks_logo.png", "docketworks_logo_wide.png"):
        source = source_dir / filename
        destination = dest_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        if source.resolve() == destination.resolve():
            continue
        shutil.copyfile(source, destination)


def _create_test_staff():
    """Create the shared test staff row — one per TestCase class.

    Deliberately neither workshop nor office staff: keeps this fixture out
    of scheduler allocation pools, payroll payloads, etc. Tests that need
    a staff with a specific role should create their own.
    """
    from apps.accounts.models import Staff

    return Staff.objects.create_user(
        email="base-test-staff@example.com",
        password="testpass",
        first_name="Test",
        last_name="Staff",
        is_workshop_staff=False,
        is_office_staff=False,
    )


class BaseTestCase(TestCase):
    """
    Base test case that loads required fixtures.

    The company_defaults fixture is required for most tests because:
    - Job creation needs CompanyDefaults (shop company, wage rate)
    - XeroPayItem (Ordinary Time) must exist for time entries

    Provides ``self.test_staff`` — a generic Staff created once per TestCase
    class — for passing to ``Job.save(staff=...)`` anywhere a test doesn't
    care about attribution. Tests that specifically assert on attribution
    should create their own Staff with a distinct identity.
    """

    fixtures = ["company_defaults"]

    test_staff: ClassVar["Staff"]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _ensure_test_media_files()
        cls.test_staff = _create_test_staff()


class BaseTransactionTestCase(TransactionTestCase):
    """
    Base transaction test case that loads required fixtures.

    Use this for tests that need transaction isolation (e.g., testing
    database constraints, concurrent access, or rollback behavior).
    """

    fixtures = ["company_defaults"]

    test_staff: "Staff"

    def setUp(self):
        super().setUp()
        _ensure_test_media_files()
        self.test_staff = _create_test_staff()


class BaseAPITestCase(APITestCase):
    """
    Base API test case that loads required fixtures.

    Use this for DRF API tests that need database access.
    """

    fixtures = ["company_defaults"]

    test_staff: ClassVar["Staff"]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _ensure_test_media_files()
        cls.test_staff = _create_test_staff()
