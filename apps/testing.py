"""
Shared test utilities and base classes for the docketworks project.

All test classes that need database models should inherit from BaseTestCase
to ensure required fixtures are loaded.
"""

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APITestCase


class BaseTestCase(TestCase):
    """
    Base test case that loads required fixtures.

    The company_defaults fixture is required for most tests because:
    - Job creation needs CompanyDefaults for charge_out_rate
    - XeroPayItem (Ordinary Time) must exist for time entries
    """

    fixtures = ["company_defaults"]


class BaseTransactionTestCase(TransactionTestCase):
    """
    Base transaction test case that loads required fixtures.

    Use this for tests that need transaction isolation (e.g., testing
    database constraints, concurrent access, or rollback behavior).
    """

    fixtures = ["company_defaults"]


class BaseAPITestCase(APITestCase):
    """
    Base API test case that loads required fixtures.

    Use this for DRF API tests that need database access.
    """

    fixtures = ["company_defaults"]
