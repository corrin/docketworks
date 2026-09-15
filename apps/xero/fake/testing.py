"""Point a test's process at the fake Xero the way run_e2e.sh points the stack at it.

Shared by the test modules of every app whose code reaches Xero (the
managers in apps.xero, the cleanup in apps.diagnostics), because the layer
contract lets a higher app import this one but not each other's tests.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.core.models import CompanyDefaults
from apps.xero.auth import _reset_api_client
from apps.xero.constants import TENANT_ID_CACHE_KEY, tenant_cache
from apps.xero.fake.minting import now_utc
from apps.xero.fake.models import FakeAccount
from apps.xero.fake.seed import (
    seed_branding_themes,
    seed_organisation,
    seed_pay_run_calendar,
    seed_tax_rates,
)
from apps.xero.models import XeroApp

THEME_ID = "11111111-2222-3333-4444-555555555555"
CALENDAR_ID = "d015dc21-981e-4d26-a9cc-f8e8432fc76d"


def seed_test_accounts(tenant_id: str) -> None:
    """Seed the two accounts the application's lines name, with the tax Xero defaults them to."""
    for code, name, tax_type, kind in (
        ("200", "Sales", "OUTPUT2", "REVENUE"),
        ("300", "Purchases", "INPUT2", "DIRECTCOSTS"),
    ):
        FakeAccount.write(
            tenant_id,
            uuid.uuid4(),
            {"Code": code, "Name": name, "TaxType": tax_type, "Status": "ACTIVE", "Type": kind},
            updated_date_utc=now_utc(),
        )


def seed_fixtures(tenant_id: str, organisation_name: str = "Test Org") -> None:
    """Seed what every seed provides: the organisation, tax rates, themes, accounts, calendar."""
    seed_organisation(tenant_id, organisation_name)
    seed_tax_rates(tenant_id)
    seed_branding_themes(tenant_id, THEME_ID)
    seed_test_accounts(tenant_id)
    seed_pay_run_calendar(tenant_id, CALENDAR_ID, "Weekly")


@contextmanager
def connected_to_the_fake(tenant_id: str) -> Iterator[str]:
    """Connect the process to the fake: an app row with a token, the flag set, fixtures seeded."""
    XeroApp.objects.create(
        label="Fake",
        client_id=f"fake-{uuid.uuid4()}",
        client_secret="s",  # noqa: S106 -- a test row; the fake never sends it anywhere
        redirect_uri="https://example.test/cb",
        is_active=True,
        access_token="stored-access-token",  # noqa: S106 -- as above
        refresh_token="stored-refresh-token",  # noqa: S106 -- as above
        token_type="Bearer",  # noqa: S106 -- a token type, not a secret
        expires_at=timezone.now() + timedelta(hours=1),
        scope="accounting.transactions payroll.employees",
    )
    CompanyDefaults.objects.filter(pk=CompanyDefaults.singleton_instance_id).update(
        xero_tenant_id=tenant_id,
        xero_sales_branding_theme_id=uuid.UUID(THEME_ID),
        xero_payroll_calendar_id=uuid.UUID(CALENDAR_ID),
    )
    CompanyDefaults.clear_cache()
    # The tenant id is also cached per process (auth.get_tenant_id); a test
    # that ran earlier in this worker may have left another tenant there, and
    # the app would then write to that tenant's store while this one reads
    # its own (CI, 2026-09-13: the cleanup test's invoice was 404 under the
    # fake's tenant). Cleared as active_app does when the active app changes.
    tenant_cache().delete(TENANT_ID_CACHE_KEY)
    seed_fixtures(tenant_id)
    _reset_api_client()
    try:
        with override_settings(XERO_FAKE=True):
            yield tenant_id
    finally:
        _reset_api_client()
        # get_tenant_id() inside the block cached this tenant; the next test in
        # the worker must not inherit it any more than this one inherited its
        # predecessor's.
        tenant_cache().delete(TENANT_ID_CACHE_KEY)
