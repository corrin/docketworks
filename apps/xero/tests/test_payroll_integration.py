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

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.accounting.types import StaffWeekPosting, StaffWeekPostResult
from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.timesheet.services.leave_settings import employee_leave_mappings
from apps.xero import payroll_push
from apps.xero.auth import get_tenant_id
from apps.xero.leave_configuration import configure_default_leave_types
from apps.xero.models import XeroPayItem
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled
from apps.xero.payroll_employees import employee_leave_type_ids, get_employee_leave_balances

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
