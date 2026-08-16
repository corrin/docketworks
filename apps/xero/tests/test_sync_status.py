"""What a sync run reports it did.

The operator reads these counts ("Synced N pay runs", "19 fetched, 0 created,
19 updated") and the per-entity sync log reads the status strings. Both were
meaningless: every transform writes ``xero_last_synced`` on every run, so every
row compared as changed and every re-sync of an unmodified organisation claimed
to have updated everything.
"""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.xero.models import XeroPayRun
from apps.xero.transforms import transform_pay_run

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stamp a tenant without a Xero token.

    Patched where the transform BOUND the name, not where it is defined:
    ``get_tenant_id`` resolves a live token before it reads CompanyDefaults, and
    this test has no business holding one.
    """
    monkeypatch.setattr("apps.xero.transforms.get_tenant_id", lambda: "sync-status-tenant")


#: Fixed, so two calls differ only where a test means them to.
CALENDAR_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _xero_pay_run(status: str = "Posted") -> SimpleNamespace:
    """A Xero pay run with the fields the transform reads."""
    return SimpleNamespace(
        payroll_calendar_id=CALENDAR_ID,
        period_start_date=date(2026, 5, 4),
        period_end_date=date(2026, 5, 10),
        payment_date=date(2026, 5, 13),
        pay_run_status=status,
        pay_run_type="Scheduled",
        total_cost=100,
        total_pay=80,
        posted_date_time=datetime(2026, 5, 13, tzinfo=UTC),
    )


class TestSyncStatus:
    def test_a_first_sync_reports_created(self) -> None:
        _, status = transform_pay_run(_xero_pay_run(), uuid.uuid4())

        assert status == "created"

    def test_re_syncing_unchanged_data_reports_unchanged(self) -> None:
        """The regression: this said "1 fields incl xero_last_synced" for every row."""
        xero_id = uuid.uuid4()
        pay_run = _xero_pay_run()
        transform_pay_run(pay_run, xero_id)

        _, status = transform_pay_run(pay_run, xero_id)

        assert status == "unchanged"

    def test_a_real_change_is_still_reported(self) -> None:
        xero_id = uuid.uuid4()
        transform_pay_run(_xero_pay_run(status="Draft"), xero_id)

        _, status = transform_pay_run(_xero_pay_run(status="Posted"), xero_id)

        assert "pay_run_status" in status

    def test_last_synced_still_advances_on_an_unchanged_row(self) -> None:
        """Persistence is unchanged; only the reporting was wrong.

        The sync-info page reads this column as "last synced", so a row that
        reports "unchanged" must still record that we looked at it.
        """
        xero_id = uuid.uuid4()
        pay_run = _xero_pay_run()
        transform_pay_run(pay_run, xero_id)
        first = XeroPayRun.objects.get(xero_id=xero_id).xero_last_synced
        assert first is not None

        transform_pay_run(pay_run, xero_id)

        second = XeroPayRun.objects.get(xero_id=xero_id).xero_last_synced
        assert second is not None
        assert second > first
