"""Which pay runs the hourly sync spends a Xero call on.

Business case: this fetcher runs hourly over every entity, so one wasted call
per pay run is 24 wasted calls a day, permanently, growing by another 24 with
every new weekly run. Measured at 20 runs it was 504 calls a day against a
development tenant allowed 1000 — half the budget before anyone ran a test.
The regression is invisible in behaviour, because re-reading a finalised run
returns exactly what the mirror already holds; only the call count shows it.
"""

from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from xero_python.payrollnz import PayRun

from apps.xero.models import XeroPayRun, XeroPaySlip
from apps.xero.payroll_sync import get_all_pay_slips_for_sync

pytestmark = pytest.mark.django_db

TENANT = "tenant-1"


def _xero_pay_run(status: str) -> tuple[PayRun, XeroPayRun]:
    xero_id = uuid4()
    mirrored = XeroPayRun.objects.create(
        xero_id=xero_id,
        xero_tenant_id=TENANT,
        period_start_date=date(2026, 8, 3),
        period_end_date=date(2026, 8, 9),
        payment_date=date(2026, 8, 12),
        pay_run_status=status,
        raw_json={},
        xero_last_modified="2026-08-12T00:00:00Z",
    )
    return PayRun(pay_run_id=str(xero_id), pay_run_status=status), mirrored


def _mirror_a_slip(pay_run: XeroPayRun) -> None:
    XeroPaySlip.objects.create(
        xero_id=uuid4(),
        xero_tenant_id=TENANT,
        pay_run=pay_run,
        xero_employee_id=uuid4(),
        raw_json={},
        xero_last_modified="2026-08-12T00:00:00Z",
    )


def _fetched_run_ids(pay_runs: list[PayRun]) -> list[str]:
    """Run the sync fetch and report which pay runs it spent a call on."""
    from apps.xero.payroll_sync import PayRunsForSync  # noqa: PLC0415

    with (
        patch(
            "apps.xero.payroll_sync.get_pay_runs_for_sync",
            return_value=PayRunsForSync(pay_runs=pay_runs),
        ),
        patch("apps.xero.payroll_sync.get_pay_slips_for_run", return_value=[]) as fetch,
        patch("apps.xero.payroll_sync._resolve_tenant_id", return_value=TENANT),
    ):
        get_all_pay_slips_for_sync()
    return [call.args[0] for call in fetch.call_args_list]


def test_a_posted_run_already_mirrored_costs_no_call() -> None:
    posted, mirrored = _xero_pay_run("Posted")
    _mirror_a_slip(mirrored)

    assert _fetched_run_ids([posted]) == []


def test_a_draft_run_is_re_read_every_time() -> None:
    # A Draft recomputes asynchronously (ADR 0007), so its slips are the one
    # thing a later sync can legitimately find changed.
    draft, mirrored = _xero_pay_run("Draft")
    _mirror_a_slip(mirrored)

    assert _fetched_run_ids([draft]) == [str(mirrored.xero_id)]


def test_a_posted_run_with_no_mirrored_slips_is_still_fetched() -> None:
    # A run posted between two syncs was never Draft while we looked. Scoping
    # on status alone would leave its slips permanently unfetched.
    posted, mirrored = _xero_pay_run("Posted")

    assert _fetched_run_ids([posted]) == [str(mirrored.xero_id)]


def test_only_the_runs_that_can_change_cost_a_call() -> None:
    # The shape production actually has: many finalised runs and one live one.
    # Twenty mirrored Posted runs cost twenty calls an hour before this.
    draft, draft_mirror = _xero_pay_run("Draft")
    _mirror_a_slip(draft_mirror)

    finalised = []
    for _ in range(19):
        posted, posted_mirror = _xero_pay_run("Posted")
        _mirror_a_slip(posted_mirror)
        finalised.append(posted)

    assert _fetched_run_ids([draft, *finalised]) == [str(draft_mirror.xero_id)]
