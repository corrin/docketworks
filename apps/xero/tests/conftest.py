"""Factories and fixtures for the Xero app's tests."""

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import timedelta
from typing import TypedDict, Unpack
from unittest.mock import Mock, patch

import pytest
from django.test import Client
from django.utils import timezone as dj_timezone

from apps.accounting.types import DocumentResult
from apps.accounts.models import Staff
from apps.core.auth import issue_refresh_token, jwt_cookie_config
from apps.platform.observability.models import VendorCall
from apps.purchasing.models import PurchaseOrder
from apps.xero.documents.po import XeroPurchaseOrderManager
from apps.xero.models import XeroApp

TEST_TENANT_ID = "test-tenant-id"

# Every path that writes a Xero id also stamps the connected tenant, and
# resolving it needs a live Xero session these suites deliberately do not have.
# Patched per binding rather than at apps.xero.auth: each module imports the
# function by name, so the source binding is not the one they call.
_TENANT_ID_BINDINGS = (
    "apps.xero.documents.invoice.get_tenant_id",
    "apps.xero.documents.po.get_tenant_id",
    "apps.xero.documents.quote.get_tenant_id",
    "apps.xero.raw_fields.get_tenant_id",
)


@pytest.fixture(autouse=True)
def xero_tenant_id(request: pytest.FixtureRequest) -> Iterator[str]:
    """Resolve the connected tenant to a fixed id for every Xero test.

    Autouse, not opt-in: an unconfigured Xero session is a property of the
    whole suite, and the alternative — a usefixtures marker on each of the
    seven modules that push or sync a document — leaves the eighth silently
    asserting a RuntimeError instead of the behaviour it was written for.

    Opus: the stored column is stamped as well as the resolver patched, because
    ``CompanyDefaults.xero_tenant_id`` is the source of truth ``get_tenant_id``
    reads and the patches only stand in for that read. Patching alone described
    a state no installation reaches — a connected session over an unbound row —
    which showed up as onboarding tests enabling sync against a tenant their own
    setup leg would have bound. Guarded on the ``django_db`` marker so a pure
    unit test pays nothing, in the shape the root conftest already uses.
    """
    if "django_db" in request.keywords:
        request.getfixturevalue("db")
        # Imported here, not at module scope: collection runs before Django's
        # app registry is populated.
        from apps.core.models import CompanyDefaults

        CompanyDefaults.objects.filter(pk=CompanyDefaults.singleton_instance_id).update(
            xero_tenant_id=TEST_TENANT_ID
        )
    with ExitStack() as stack:
        for target in _TENANT_ID_BINDINGS:
            stack.enter_context(patch(target, return_value=TEST_TENANT_ID))
        yield TEST_TENANT_ID


class XeroAppOverrides(TypedDict, total=False):
    """The XeroApp columns tests vary."""

    label: str
    client_id: str
    client_secret: str
    redirect_uri: str
    is_active: bool
    webhook_key: str | None
    access_token: str | None
    refresh_token: str | None
    token_type: str | None
    expires_at: object
    scope: str | None


def make_xero_app(**overrides: Unpack[XeroAppOverrides]) -> XeroApp:
    """Create a XeroApp row; inactive with no tokens unless overridden."""
    defaults: XeroAppOverrides = {
        "label": "A",
        "client_id": "c-a",
        "client_secret": "s",
        "redirect_uri": "https://example.test/cb",
        "is_active": False,
    }
    defaults.update(overrides)
    return XeroApp.objects.create(**defaults)


def record_xero_quota(
    day_remaining: int | None, minute_remaining: int = 60, age_seconds: int = 0
) -> None:
    """Make the vendor-call log say Xero last reported this much quota left."""
    VendorCall.objects.create(
        vendor=VendorCall.Vendor.XERO,
        method="GET",
        endpoint="/api.xro/2.0/Invoices",
        occurred_at=dj_timezone.now() - timedelta(seconds=age_seconds),
        duration_ms=1,
        status_code=200,
        day_remaining=day_remaining,
        minute_remaining=minute_remaining,
    )


@pytest.fixture
def non_office_api() -> Client:
    """An authenticated client whose staff member is NOT office staff."""
    staff: Staff = Staff.objects.create_user(
        office_email="floor@example.test",
        password="s3cret-Pass!",
        first_name="Floor",
        last_name="Staff",
        is_office_staff=False,
    )
    client = Client()
    refresh = issue_refresh_token(staff)
    client.cookies[jwt_cookie_config().access_name] = str(refresh.access_token)
    return client


def make_po_manager(po: PurchaseOrder, provider: Mock) -> XeroPurchaseOrderManager:
    """Bind a PO to the fake provider boundary."""
    with patch("apps.xero.documents.base.get_provider", return_value=provider):
        return XeroPurchaseOrderManager(purchase_order=po, staff=Staff.get_automation_user())


def make_po_provider(result: DocumentResult | None = None) -> Mock:
    """A provider accepting purchase orders without contacting Xero."""
    provider = Mock()
    provider.get_account_code.return_value = "300"
    if result is not None:
        provider.create_purchase_order.return_value = result
        provider.update_purchase_order.return_value = result
    return provider
