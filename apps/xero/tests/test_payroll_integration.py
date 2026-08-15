"""The Xero payroll write path, against the real Xero tenant.

Marked ``integration``, so the default suite skips it and
``./scripts/ops/run_integration_tests.sh`` runs it (ADR 0050). Nothing here
uses a fake: a fake returns what the author already assumed, which is how a
payroll path that could not post at all passed a full unit suite, strict mypy
and a green E2E spec.

**Idempotent by design.** Xero's Payroll API has no ``delete_pay_run``, so a
created draft is permanent on the tenant. These tests therefore drive
``ensure_pay_run_for_week``, which reuses a same-week draft: the first run
creates one, every later run reuses it. Timesheets *can* be deleted, so those
are cleaned up. Run the suite twice — the second pass is what proves this is a
test rather than a probe.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.xero import payroll_push
from apps.xero.operator_guards import assert_not_production_target, assert_xero_writes_enabled

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _guards(integration_credentials: None) -> None:  # noqa: ARG001 -- requesting it IS the dependency: real credentials must be in place before any guard runs
    """Refuse a production target, and refuse a run that cannot write.

    Both refuse rather than skip. A skipped integration test is
    indistinguishable from a passing one in a summary line, which is the exact
    failure this suite exists to correct.
    """
    assert_not_production_target()
    assert_xero_writes_enabled("the payroll integration suite")


@pytest.fixture
def postable_week() -> date:
    """The one week Xero will currently accept a pay run for."""
    calendar_id = CompanyDefaults.get_solo().xero_payroll_calendar_id
    if calendar_id is None:
        raise RuntimeError(
            "No xero_payroll_calendar_id. Run `python manage.py xero --setup` before "
            "the payroll integration suite."
        )
    # The domain service owns this rule and the page reads its answer, so the
    # test asks the same question the product asks (apps.xero sits above the
    # domain apps, so importing it here is with the layer contract).
    from apps.timesheet.services import payroll_service  # noqa: PLC0415

    week = payroll_service.next_postable_payroll_week(calendar_id)
    if week is None:
        raise RuntimeError("Xero reports no postable week for the configured payroll calendar.")
    return week[0]


class TestPostableWeek:
    def test_it_is_a_plain_date_not_a_datetime(self, postable_week: date) -> None:
        """The defect that disabled posting on the real system.

        Xero returns datetimes for these fields and ``datetime`` subclasses
        ``date``, so an isinstance check — and mypy, and every fake — accepts a
        datetime here. It then serialises as "2026-07-13T00:00:00" where the
        wire promises "2026-07-13", the page's week comparison never matches,
        and Post is disabled forever.
        """
        assert type(postable_week) is date

    def test_it_is_a_monday(self, postable_week: date) -> None:
        """Xero pay periods are Monday-anchored; anything else posts to the wrong period."""
        assert postable_week.weekday() == 0


class TestPayRunLifecycle:
    def test_refresh_mirrors_what_xero_holds(self) -> None:
        result = payroll_push.refresh_pay_runs()

        assert result.fetched >= 0
        assert result.created + result.updated <= result.fetched

    def test_ensuring_the_pay_run_twice_reuses_the_same_draft(self, postable_week: date) -> None:
        """Xero allows one draft per calendar, so a second create would 409.

        This is also what makes the suite re-runnable at all: there is no API
        to delete the draft the first run created.
        """
        first = payroll_push.ensure_pay_run_for_week(postable_week)
        second = payroll_push.ensure_pay_run_for_week(postable_week)

        assert first.pay_run_id == second.pay_run_id
        assert first.pay_run_status == "Draft"
        assert first.period_start_date == postable_week


def _posted_hours(week: date, staff: Staff) -> Decimal:
    """What Xero holds for this staff member's week, via the app's own read."""
    [status] = [
        row for row in payroll_push.week_posting_status(week) if row.staff_id == str(staff.id)
    ]
    return status.posted_hours


class TestPostingAWeek:
    """Post real hours, then ask Xero what it holds."""

    def test_posting_then_re_posting_replaces_rather_than_duplicates(
        self, postable_week: date, payroll_staff: Staff, work_line: CostLine
    ) -> None:
        payroll_push.ensure_pay_run_for_week(postable_week)

        [posted] = list(payroll_push.post_payroll_week([payroll_staff.id], postable_week))
        assert posted.success, posted.error
        # Read it back. Asserting the call returned success would reproduce
        # exactly the blind spot a fake has.
        assert _posted_hours(postable_week, payroll_staff) == work_line.quantity

        # ADR 0007 promises replacement; the failure this guards is Xero
        # accumulating both figures.
        work_line.quantity += 1
        work_line.save(update_fields=["quantity"])
        list(payroll_push.post_payroll_week([payroll_staff.id], postable_week))

        assert _posted_hours(postable_week, payroll_staff) == work_line.quantity

    @pytest.mark.usefixtures("work_line")
    def test_posting_the_same_hours_twice_does_not_double_them(
        self, postable_week: date, payroll_staff: Staff
    ) -> None:
        """The re-post an operator makes when unsure whether the first one worked."""
        payroll_push.ensure_pay_run_for_week(postable_week)
        list(payroll_push.post_payroll_week([payroll_staff.id], postable_week))
        once = _posted_hours(postable_week, payroll_staff)

        list(payroll_push.post_payroll_week([payroll_staff.id], postable_week))

        assert _posted_hours(postable_week, payroll_staff) == once


@pytest.fixture
def payroll_staff() -> Staff:
    """A staff member the restored database has actually linked to a Xero employee.

    Taken from the data rather than created: the link between a local Staff row
    and a Xero employee is itself a production failure mode, so a manufactured
    one would prove nothing.
    """
    staff = (
        Staff.objects.exclude(xero_user_id__isnull=True)
        .exclude(xero_user_id="")
        .order_by("email")
        .first()
    )
    if staff is None:
        raise RuntimeError(
            "No Staff row carries a xero_user_id. Link staff to Xero employees before "
            "running the payroll integration suite."
        )
    return staff


@pytest.fixture
def work_line(payroll_staff: Staff, postable_week: date) -> CostLine:
    """One time line in the postable week, built by the same factory the unit tests use.

    ``make_time_line`` rather than a hand-built CostLine: a bespoke one here
    would be a second definition of what a timesheet line looks like, free to
    drift from the real one — and then this test would prove Xero accepts a
    shape the application never sends.
    """
    from apps.company.tests.conftest import make_company  # noqa: PLC0415
    from apps.company.tests.job_fixtures import make_job  # noqa: PLC0415
    from apps.timesheet.tests.conftest import make_time_line  # noqa: PLC0415

    company = make_company("[TEST] Payroll Integration")
    job = make_job(company, payroll_staff, name="[TEST] Payroll Integration Job")
    return make_time_line(
        job, payroll_staff, accounting_date=postable_week + timedelta(days=1), hours="1.000"
    )
