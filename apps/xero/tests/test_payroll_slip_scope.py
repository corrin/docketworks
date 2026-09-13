"""Which pay runs the hourly sync spends a Xero call on.

Business case: this fetcher runs hourly over every entity, so one wasted call
per pay run is 24 wasted calls a day, permanently, growing by another 24 with
every new weekly run. Measured at 20 runs it was 504 calls a day against a
development tenant allowed 1000 — half the budget before anyone ran a test.
The regression is invisible in behaviour, because re-reading a finalised run
returns exactly what the mirror already holds; only the call count shows it.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from xero_python.payrollnz import PayRun

from apps.xero.models import XeroPayRun, XeroPaySlip
from apps.xero.payroll_sync import get_all_pay_slips_for_sync

pytestmark = pytest.mark.django_db

TENANT = "tenant-1"


def _xero_pay_run(status: str, *, pay_slip_count: int | None = None) -> tuple[PayRun, XeroPayRun]:
    xero_id = uuid4()
    mirrored = XeroPayRun.objects.create(
        xero_id=xero_id,
        xero_tenant_id=TENANT,
        pay_slip_count=pay_slip_count,
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
    posted, mirrored = _xero_pay_run("Posted", pay_slip_count=1)
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
        posted, posted_mirror = _xero_pay_run("Posted", pay_slip_count=1)
        _mirror_a_slip(posted_mirror)
        finalised.append(posted)

    assert _fetched_run_ids([draft, *finalised]) == [str(draft_mirror.xero_id)]


def test_a_partial_posted_run_is_read_again_until_every_slip_is_mirrored() -> None:
    """One persisted slip is not a mirrored run: production has genuine one-slip runs.

    Persistence is per slip and continues past a failure, so a batch cut
    short leaves a run with fewer rows than Xero reported. Such a run must be
    read again on the next sync, and stop costing a call once it is whole.
    """
    from apps.xero.payroll_sync import PayRunsForSync  # noqa: PLC0415
    from apps.xero.sync import _persist_pay_slips  # noqa: PLC0415
    from apps.xero.transforms import transform_pay_slip  # noqa: PLC0415

    posted, mirrored = _xero_pay_run("Posted")
    slips = [
        SimpleNamespace(
            pay_slip_id=str(uuid4()),
            pay_run_id=str(mirrored.xero_id),
            employee_id=str(uuid4()),
            first_name=name,
            last_name="Employee",
            gross_earnings=100,
            tax=20,
            net_pay=80,
        )
        for name in ("First", "Second")
    ]

    def fetched_and_persisted(fail_second: bool) -> list[str]:
        def transform(
            slip: object, xero_id: UUID | str, *, tenant_id: str
        ) -> tuple[XeroPaySlip, str] | None:
            if fail_second and slip is slips[1]:
                raise RuntimeError("Transient failure while persisting the second slip")
            return transform_pay_slip(slip, xero_id, tenant_id=tenant_id)

        with (
            patch(
                "apps.xero.payroll_sync.get_pay_runs_for_sync",
                return_value=PayRunsForSync(pay_runs=[posted]),
            ),
            patch("apps.xero.payroll_sync.get_pay_slips_for_run", return_value=slips) as fetch,
            patch("apps.xero.payroll_sync._resolve_tenant_id", return_value=TENANT),
            patch("apps.xero.sync.transform_pay_slip", side_effect=transform),
        ):
            batch = get_all_pay_slips_for_sync().pay_slips
            _persist_pay_slips(list(batch), TENANT)
        return [call.args[0] for call in fetch.call_args_list]

    assert fetched_and_persisted(fail_second=True) == [str(mirrored.xero_id)]
    assert XeroPaySlip.objects.filter(pay_run=mirrored).count() == 1

    assert fetched_and_persisted(fail_second=False) == [str(mirrored.xero_id)]
    assert XeroPaySlip.objects.filter(pay_run=mirrored).count() == 2

    assert fetched_and_persisted(fail_second=False) == [], "a whole run costs no further call"
