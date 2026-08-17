"""The complete weekly payroll write path against the real demo tenant.

This is intentionally one stateful scenario. Xero state survives pytest while
the local test database does not, so independent mutation tests lie about
their starting state. The scenario establishes all four Docketworks leave
types, posts, changes and re-posts, restores and re-posts, then proves an
unchanged re-post is a no-op. Run it twice.

Xero exposes no pay-run delete API. If the demo tenant contains a stale Draft
whose leave differs from this scenario, delete that Draft in the Xero UI before
the first clean run; the application will report that operator action rather
than trying to work around Xero's lock.
"""

import time
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.accounting.services import payroll_reconciliation_service
from apps.accounting.types import StaffWeekPosting, StaffWeekPostResult
from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.timesheet.services.leave_settings import employee_leave_mappings
from apps.xero import payroll_push
from apps.xero.auth import get_tenant_id
from apps.xero.leave_configuration import configure_default_leave_types
from apps.xero.models import XeroPayItem, XeroPaySlip
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.payroll_employees import employee_leave_type_ids, get_employee_leave_balances
from apps.xero.payroll_sync import get_pay_slips_for_run
from apps.xero.transforms import transform_pay_slip

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _guards(integration_credentials: None) -> None:  # noqa: ARG001
    assert_not_production_target()
    assert_xero_writes_enabled("the payroll integration suite")
    payroll_push.refresh_pay_runs()


@pytest.fixture
def postable_week() -> date:
    calendar_id = CompanyDefaults.get_solo().xero_payroll_calendar_id
    if calendar_id is None:
        raise RuntimeError("Run `python manage.py xero --setup` before payroll integration tests.")
    from apps.timesheet.services import payroll_service  # noqa: PLC0415

    week = payroll_service.next_postable_payroll_week(calendar_id)
    if week is None:
        raise RuntimeError("Xero reports no postable week for the configured payroll calendar.")
    assert type(week[0]) is date
    assert week[0].weekday() == 0
    return week[0]


@pytest.fixture
def payroll_staff(postable_week: date) -> Staff:
    staff = (
        Staff.objects.active_between_dates(postable_week, postable_week + timedelta(days=6))
        .filter(xero_tenant_id=get_tenant_id())
        .exclude(xero_user_id__isnull=True)
        .exclude(xero_user_id="")
        .order_by("email")
        .first()
    )
    if staff is None:
        raise RuntimeError("Run `seed_xero_from_database --only=employees` before this suite.")
    return staff


@pytest.fixture
def payroll_lines(payroll_staff: Staff, postable_week: date) -> list[CostLine]:
    from apps.company.tests.conftest import make_company  # noqa: PLC0415
    from apps.company.tests.job_fixtures import make_job  # noqa: PLC0415
    from apps.timesheet.tests.conftest import make_time_line  # noqa: PLC0415

    # Migrations precede the integration credential fixture, so the blank test
    # database cannot bind tenant pay items during its data migration. Converge
    # in the same post-sync order as production onboarding.
    call_command("create_shop_jobs")
    configure_default_leave_types()
    tenant_id = get_tenant_id()
    mappings = employee_leave_mappings()
    leave_items = {
        str(item.xero_id): item
        for item in XeroPayItem.objects.filter(
            xero_tenant_id=tenant_id,
            uses_leave_api=True,
            xero_id__in=[mapping.external_id for mapping in mappings],
        ).exclude(xero_id__isnull=True)
    }
    missing = [
        mapping.display_name for mapping in mappings if mapping.external_id not in leave_items
    ]
    if missing:
        raise RuntimeError("Missing tenant leave mappings: " + ", ".join(missing))

    company = make_company("[TEST] Payroll Integration")
    work_job = make_job(company, payroll_staff, name="[TEST] Payroll Work")
    lines = [
        make_time_line(
            work_job,
            payroll_staff,
            accounting_date=postable_week + timedelta(days=4),
            hours="1.000",
        )
    ]
    for offset, mapping in enumerate(mappings):
        job = make_job(company, payroll_staff, name=f"[TEST] {mapping.display_name}")
        job.default_xero_pay_item = leave_items[mapping.external_id]
        job.save(update_fields=["default_xero_pay_item"], staff=payroll_staff)
        lines.append(
            make_time_line(
                job,
                payroll_staff,
                accounting_date=postable_week + timedelta(days=offset),
                hours="1.000",
            )
        )
    return lines


def _status(week: date, staff: Staff) -> StaffWeekPosting:
    return next(
        row for row in payroll_push.week_posting_status(week) if row.staff_id == str(staff.id)
    )


def _post(week: date, staff: Staff) -> StaffWeekPostResult:
    [result] = list(payroll_push.post_payroll_week([staff.id], week))
    assert result.success, result.error
    assert not result.skipped, result.reason
    return result


def test_live_employee_leave_balances_cover_configured_mappings(
    payroll_staff: Staff,
    payroll_lines: list[CostLine],
) -> None:
    """The provider returns live balances for every mapped Docketworks leave type."""
    assert payroll_lines  # fixture establishes the post-onboarding mappings
    required_ids = {mapping.external_id for mapping in employee_leave_mappings()}
    assigned_ids = employee_leave_type_ids(str(payroll_staff.xero_user_id))
    balance_ids = {
        balance.leave_type_external_id
        for balance in get_employee_leave_balances(str(payroll_staff.xero_user_id))
    }

    assert required_ids <= assigned_ids
    assert required_ids <= balance_ids


#: Xero recomputes a Draft pay run's pay slips asynchronously after an
#: underlying timesheet changes: a slip read immediately after posting still
#: carries the PREVIOUS figures, and catches up within about two minutes.
#: Measured on 2026-08-17 — a slip read 59s after a 1.000 -> 1.250 re-post
#: reported 1.00, and the same slip read at 2m17s reported 1.25.
PAYSLIP_SETTLE_TIMEOUT_SECONDS = 240
PAYSLIP_POLL_SECONDS = 15


def _fetch_payslip(pay_run_id: str, staff: Staff) -> XeroPaySlip:
    """Xero's own computed pay slip for this employee, as the read side parses it."""
    mine = [
        slip
        for slip in get_pay_slips_for_run(pay_run_id)
        if str(slip.employee_id) == str(staff.xero_user_id)
    ]
    assert len(mine) == 1, (
        f"Xero holds {len(mine)} pay slips for {staff.get_display_full_name()} "
        f"in pay run {pay_run_id}"
    )
    transformed = transform_pay_slip(mine[0], str(mine[0].pay_slip_id))
    assert transformed is not None, "the pay run mirror did not carry this slip's parent"
    return transformed[0]


def _assert_xero_computed(week: date, staff: Staff, posted: StaffWeekPostResult) -> None:
    """Make Xero's own arithmetic confirm the hours, split the way ADR 0007 routes.

    The independent channel. Every other read-back in this file goes through
    ``payroll_push`` / ``payroll_leave`` — the same modules that wrote — so a
    wrong belief about Xero's contract would be written and read the same wrong
    way and the assertion would still pass. A pay slip is Xero computing
    earnings from the timesheet and leave records IT holds, delivered on a
    different endpoint and parsed by the read side's ``transform_pay_slip``,
    which shares no code with the write path.

    The split across timesheet and leave earnings is the part a matching
    misunderstanding cannot fake: hours paid as an earnings rate ride the
    timesheet, and only ``uses_leave_api`` hours reach the leave surface, which
    is the one that debits a balance.

    Polled rather than read once, because of the recompute lag above. The poll
    has a deadline and reports both figures when it expires — it never passes on
    a timeout, which would turn this assertion back into the thing it replaced.
    """
    pay_run = payroll_push.ensure_pay_run_for_week(week)
    # transform_pay_slip resolves each slip's parent from the XeroPayRun table,
    # so the mirror has to hold the run the post just used.
    payroll_push.refresh_pay_runs()
    expected_timesheet = posted.work_hours + posted.other_leave_hours
    expected_leave = posted.leave_hours

    deadline = time.monotonic() + PAYSLIP_SETTLE_TIMEOUT_SECONDS
    slip = _fetch_payslip(pay_run.pay_run_id, staff)
    while (slip.timesheet_hours, slip.leave_hours) != (expected_timesheet, expected_leave):
        if time.monotonic() >= deadline:
            raise AssertionError(
                "Xero's pay slip never agreed with what we posted: it computed "
                f"{slip.timesheet_hours}h timesheet / {slip.leave_hours}h leave, we posted "
                f"{expected_timesheet}h / {expected_leave}h, after "
                f"{PAYSLIP_SETTLE_TIMEOUT_SECONDS}s in pay run {pay_run.pay_run_id}."
            )
        time.sleep(PAYSLIP_POLL_SECONDS)
        slip = _fetch_payslip(pay_run.pay_run_id, staff)

    assert slip.gross_earnings > Decimal("0")


def test_live_week_reconciliation_sees_both_sides_and_the_unposted_employee(
    postable_week: date,
    payroll_staff: Staff,
    payroll_lines: list[CostLine],
) -> None:
    """The money reconciliation answers straight after posting, from Xero's own figures.

    Two things are proven here that a mirror-backed report cannot be:

    First, it answers at all. ``get_reconciliation_data`` reads the synced
    ``XeroPaySlip`` mirror, which exists only once the run is Posted and a sync
    has mirrored it — so it is blank in the minutes after posting, which is
    exactly when a mistake is still cheap to fix.

    Second, and this is the costly case, it is driven from XERO's slips rather
    than our staff list. An employee Xero holds on the calendar that we posted
    nothing for is paid their pay-template hours — typically a full week nobody
    worked — and no amount of iterating the staff DocketWorks knows will ever
    surface them. They appear here as ``xero_only``.
    """
    assert payroll_lines
    posted = _post(postable_week, payroll_staff)
    assert posted.work_hours + posted.leave_hours > Decimal("0")

    # Dollars are the test. Hours agreeing is necessary and not sufficient:
    # the same hours at the wrong rate pay the wrong money, and money is what
    # leaves the bank.
    #
    # Close, not equal. DocketWorks is a management system and is right to
    # about a percent; Xero is a payroll system and is exact, applying rules
    # DocketWorks does not model. So the standard is that the two track each
    # other, which is what `status == "ok"` means.
    deadline = time.monotonic() + PAYSLIP_SETTLE_TIMEOUT_SECONDS
    while True:
        result = payroll_reconciliation_service.get_week_reconciliation(postable_week)
        rows = {row["name"]: row for row in result["week"]["staff"]}
        mine = rows.get(payroll_staff.get_display_name())
        if mine is not None and mine["status"] == "ok":
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                "Xero's pay slip never came within tolerance of what we posted: "
                f"DocketWorks base pay {mine['jm_base_pay'] if mine else None}, "
                f"Xero gross {mine['xero_gross'] if mine else None}, "
                f"diff {mine['pay_diff'] if mine else None}, "
                f"status {mine['status'] if mine else None}; row={mine}"
            )
        time.sleep(PAYSLIP_POLL_SECONDS)

    assert result["xero_source"] == "live_run"
    assert mine is not None
    # Real money, not two zeroes agreeing with each other.
    assert mine["xero_gross"] > 0.0
    assert mine["jm_base_pay"] > 0.0
    # Base is what reconciles; loaded carries the annual leave loading Xero
    # does not pay, so it sits above the gross by that much.
    assert mine["jm_base_pay"] < mine["jm_cost"]
    assert mine["hours_diff"] == 0.0

    # The employees Xero would pay that we posted nothing for.
    assert [row["name"] for row in result["week"]["staff"] if row["status"] == "xero_only"], (
        "the demo tenant's other payroll employees should surface as xero_only; "
        "a reconciliation that cannot see them cannot see the costliest error"
    )


def test_complete_weekly_payroll_lifecycle(
    postable_week: date,
    payroll_staff: Staff,
    payroll_lines: list[CostLine],
) -> None:
    mappings = employee_leave_mappings()
    required_ids = {mapping.external_id for mapping in mappings}
    assigned_ids = employee_leave_type_ids(str(payroll_staff.xero_user_id))
    assert required_ids <= assigned_ids
    balance_ids = {
        balance.leave_type_external_id
        for balance in get_employee_leave_balances(str(payroll_staff.xero_user_id))
    }
    assert required_ids <= balance_ids

    initial_work = Decimal("1.000")
    initial_leave = Decimal("4.000")
    first = _post(postable_week, payroll_staff)
    assert (first.work_hours, first.leave_hours) == (initial_work, initial_leave)
    first_status = _status(postable_week, payroll_staff)
    assert first_status.posted_timesheet_hours == initial_work
    assert first_status.posted_leave_hours == initial_leave
    assert first_status.matches

    for line in payroll_lines:
        line.quantity += Decimal("0.250")
        line.save(update_fields=["quantity"])
    changed = _post(postable_week, payroll_staff)
    assert (changed.work_hours, changed.leave_hours) == (Decimal("1.250"), Decimal("5.000"))
    changed_status = _status(postable_week, payroll_staff)
    assert changed_status.posted_timesheet_hours == Decimal("1.250")
    assert changed_status.posted_leave_hours == Decimal("5.000")
    assert changed_status.matches
    # The decisive one: this stage deleted and recreated a real timesheet, so
    # Xero recomputing 1.250/5.000 proves the write landed rather than that two
    # readings of our own belief agree.
    _assert_xero_computed(postable_week, payroll_staff, changed)

    for line in payroll_lines:
        line.quantity -= Decimal("0.250")
        line.save(update_fields=["quantity"])
    restored = _post(postable_week, payroll_staff)
    assert (restored.work_hours, restored.leave_hours) == (initial_work, initial_leave)
    restored_status = _status(postable_week, payroll_staff)
    assert restored_status.posted_timesheet_hours == initial_work
    assert restored_status.posted_leave_hours == initial_leave
    assert restored_status.matches

    week = payroll_push._WeekWindow.of(postable_week)
    before_id = payroll_push.existing_timesheets_for_week(week)[
        str(payroll_staff.xero_user_id)
    ].timesheet_id
    unchanged = _post(postable_week, payroll_staff)
    after_id = payroll_push.existing_timesheets_for_week(week)[
        str(payroll_staff.xero_user_id)
    ].timesheet_id
    assert unchanged.work_hours == initial_work
    assert unchanged.leave_hours == initial_leave
    assert after_id == before_id
    assert _status(postable_week, payroll_staff).matches
