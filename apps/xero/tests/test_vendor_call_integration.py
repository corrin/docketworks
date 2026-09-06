"""Xero calls reach the vendor-call log (ADR 0050).

A fake cannot prove this. The number recorded is Xero's own remaining-quota
header, so a test that supplied it would only confirm what we already believed
— which is exactly how the quota came to be unexplainable.

The Xero half lives here rather than beside the recorder: ``apps.platform`` may
not import ``apps.xero`` (ADR 0055), and "does the Xero seam record?" is a
question about the Xero context.

Read-only: it lists organisations, the cheapest call the connection offers, and
writes nothing anywhere.
"""

import pytest
from xero_python.accounting import AccountingApi

from apps.platform.observability.models import VendorCall
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.operator_guards import assert_not_production_target

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _credentials(integration_credentials: None) -> None:
    """Bring the Xero credentials across from the dev database (ADR 0050)."""


def test_a_real_call_records_the_quota_xero_reported() -> None:
    assert_not_production_target()
    VendorCall.objects.all().delete()

    # Drive the application's own client, never a hand-built request: a test
    # that made its own call would prove the vendor accepts a shape the
    # application never sends (ADR 0050).
    AccountingApi(get_api_client()).get_organisations(get_tenant_id())

    rows = list(VendorCall.objects.filter(vendor=VendorCall.Vendor.XERO))
    assert rows, "a real Xero call left no row in the log"
    # Asserted by reading the vendor's own header back off the row rather than
    # by the call having returned: the header is the thing under test.
    assert any(row.day_remaining is not None for row in rows), (
        "no recorded Xero call carried X-DayLimit-Remaining"
    )
    for row in rows:
        assert row.endpoint.startswith("/api.xro/")
        assert row.status_code == 200
        if row.day_remaining is not None:
            # The dev tenant allows 1000/day, production 5000. A reading
            # outside that range means the header was misparsed, not that the
            # quota is unusual.
            assert 0 <= row.day_remaining <= 5000
