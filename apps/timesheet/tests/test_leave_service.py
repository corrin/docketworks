"""Leave requests as first-class records with CostLine payroll projections."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db.models import Model
from django.utils import timezone

from apps.accounting.types import PayrollLeaveBalance
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services import job_service
from apps.timesheet.models import LeaveDay, LeaveRequest, LeaveType
from apps.timesheet.services import leave_service, leave_settings
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = pytest.mark.django_db


def next_monday() -> date:
    """The next Monday strictly after today.

    Computed rather than hardcoded: ``list_leave_requests`` splits current from
    history on ``end_date >= today``, so a fixed date passes only until the
    clock rolls past it — a suite that goes red overnight with no commit
    behind it. A Monday specifically, because staff scheduled hours are
    per-weekday and these tests assert an 8-hour day.
    """
    today = timezone.localdate()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


MONDAY = next_monday()
TUESDAY = MONDAY + timedelta(days=1)


def configure_type(
    *, code: str, name: str, job: Job, superuser: Staff, uses_leave_api: bool = True
) -> LeaveType:
    defaults = CompanyDefaults.get_solo()
    pay_item_model = django_apps.get_model("xero", "XeroPayItem")
    pay_item, _created = pay_item_model.objects.update_or_create(
        name=name if uses_leave_api else "Ordinary Time",
        uses_leave_api=uses_leave_api,
        defaults={
            "xero_id": f"xero-{code}",
            "xero_tenant_id": defaults.xero_tenant_id,
            "multiplier": None if uses_leave_api else Decimal("1.00"),
        },
    )
    job.status = "special"
    job.default_xero_pay_item_id = pay_item.pk
    job.save(staff=superuser, update_fields=["status", "default_xero_pay_item", "updated_at"])
    leave_type = LeaveType.objects.get(code=code)
    leave_type.display_name = name
    leave_type.job = job
    leave_type.save(update_fields=["display_name", "job", "updated_at"])
    return leave_type


def requested(*days: tuple[date, str]) -> list[leave_service.RequestedDay]:
    return [{"date": day, "hours": Decimal(hours)} for day, hours in days]


def test_create_request_projects_partial_days_to_payroll_lines(
    worker: Staff, job: Job, superuser: Staff
) -> None:
    leave_type = configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )

    result = leave_service.create_leave_request(
        staff_id=worker.id,
        leave_type_code=leave_type.code,
        start_date=MONDAY,
        end_date=TUESDAY,
        note="Family trip",
        requested_days=requested((MONDAY, "4"), (TUESDAY, "8")),
        actor=superuser,
    )

    request = LeaveRequest.objects.get(id=UUID(result["request"]["id"]))
    assert request.days.count() == 2
    assert result["request"]["total_hours"] == Decimal("12")
    lines = CostLine.objects.filter(managed_by="leave").order_by("accounting_date")
    assert list(lines.values_list("quantity", flat=True)) == [Decimal("4"), Decimal("8")]
    assert all(line.staff_id == worker.id for line in lines)
    assert all(line.xero_pay_item_id == job.default_xero_pay_item_id for line in lines)
    assert all(line.meta["is_billable"] is False for line in lines)
    assert all(line.approved for line in lines)


def test_conflicting_days_are_skipped_but_available_days_are_saved(
    worker: Staff, job: Job, superuser: Staff
) -> None:
    configure_type(code=LeaveType.Code.SICK, name="Sick Leave", job=job, superuser=superuser)
    make_time_line(job, worker, accounting_date=MONDAY)

    result = leave_service.create_leave_request(
        staff_id=worker.id,
        leave_type_code=LeaveType.Code.SICK,
        start_date=MONDAY,
        end_date=TUESDAY,
        note=None,
        requested_days=requested((MONDAY, "8"), (TUESDAY, "8")),
        actor=superuser,
    )

    assert [day["date"] for day in result["skipped_days"]] == [MONDAY]
    assert [day.date for day in LeaveDay.objects.all()] == [TUESDAY]


def test_update_replaces_days_and_delete_removes_every_projection(
    worker: Staff, job: Job, superuser: Staff
) -> None:
    configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )
    created = leave_service.create_leave_request(
        staff_id=worker.id,
        leave_type_code=LeaveType.Code.ANNUAL,
        start_date=MONDAY,
        end_date=MONDAY,
        note=None,
        requested_days=requested((MONDAY, "8")),
        actor=superuser,
    )
    request_id = UUID(created["request"]["id"])
    old_line_id = LeaveDay.objects.get().cost_line_id

    updated = leave_service.update_leave_request(
        request_id=request_id,
        leave_type_code=LeaveType.Code.ANNUAL,
        start_date=TUESDAY,
        end_date=TUESDAY,
        note="Changed",
        requested_days=requested((TUESDAY, "3")),
        actor=superuser,
    )

    assert not CostLine.objects.filter(id=old_line_id).exists()
    assert updated["request"]["total_hours"] == Decimal("3")
    leave_service.delete_leave_request(request_id)
    assert not LeaveRequest.objects.exists()
    assert not LeaveDay.objects.exists()
    assert not CostLine.objects.filter(managed_by="leave").exists()


def test_generic_cost_line_writes_refuse_managed_leave(
    worker: Staff, job: Job, superuser: Staff
) -> None:
    configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )
    leave_service.create_leave_request(
        staff_id=worker.id,
        leave_type_code=LeaveType.Code.ANNUAL,
        start_date=MONDAY,
        end_date=MONDAY,
        note=None,
        requested_days=requested((MONDAY, "8")),
        actor=superuser,
    )
    line = CostLine.objects.get(managed_by="leave")

    with pytest.raises(ValueError, match="Timesheets → Leave"):
        job_service.update_cost_line(line, {"quantity": Decimal("4")})
    with pytest.raises(ValueError, match="Timesheets → Leave"):
        job_service.delete_cost_line(line)


def test_balance_uses_configured_external_id(
    monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job, superuser: Staff
) -> None:
    configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )
    provider = SimpleNamespace(
        get_payroll_leave_balances=lambda _employee_id: [
            PayrollLeaveBalance(
                leave_type_external_id="xero-annual_leave",
                name="Annual Leave",
                balance=Decimal("72.5"),
                unit="Hours",
            )
        ]
    )
    monkeypatch.setattr(leave_service, "get_provider", lambda: provider)

    assert leave_service.get_leave_balance(staff=worker, leave_type_code=LeaveType.Code.ANNUAL) == {
        "balance": Decimal("72.5"),
        "unit": "Hours",
        "name": "Annual Leave",
    }


def update_row(
    leave_type: LeaveType, *, name: str | None = None
) -> leave_settings.LeaveTypeUpdateData:
    """The row a settings page submits for an already-configured type."""
    job = leave_type.job
    assert job is not None
    return leave_settings.LeaveTypeUpdateData(
        code=leave_type.code,
        display_name=name if name is not None else leave_type.display_name,
        job_id=job.id,
        xero_pay_item_id=job.default_xero_pay_item_id,
    )


def test_mapping_update_changes_job_default_and_rejects_wrong_surface(
    job: Job, superuser: Staff
) -> None:
    configure_type(
        code=LeaveType.Code.ANNUAL,
        name="Annual Leave",
        job=job,
        superuser=superuser,
    )
    pay_item_model = django_apps.get_model("xero", "XeroPayItem")
    ordinary = pay_item_model.objects.get(name="Ordinary Time", uses_leave_api=False)

    with pytest.raises(ValidationError, match="requires a Xero leave type"):
        leave_settings.update_leave_types(
            updates=[
                leave_settings.LeaveTypeUpdateData(
                    code=LeaveType.Code.ANNUAL,
                    display_name="Holiday",
                    job_id=job.id,
                    xero_pay_item_id=ordinary.id,
                )
            ],
            actor=superuser,
        )


def test_a_rejected_row_rolls_back_the_rows_saved_beside_it(
    company: Company, job: Job, superuser: Staff
) -> None:
    """The reason this endpoint takes a list: a loop would leave row 1 written."""
    annual = configure_type(
        code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
    )
    sick_job = make_job(company, superuser, name="Sick Leave Job")
    configure_type(code=LeaveType.Code.SICK, name="Sick Leave", job=sick_job, superuser=superuser)
    pay_item_model = django_apps.get_model("xero", "XeroPayItem")
    ordinary = pay_item_model.objects.get(name="Ordinary Time", uses_leave_api=False)

    with pytest.raises(ValidationError, match="requires a Xero leave type"):
        leave_settings.update_leave_types(
            updates=[
                update_row(annual, name="Renamed Annual"),
                leave_settings.LeaveTypeUpdateData(
                    code=LeaveType.Code.SICK,
                    display_name="Renamed Sick",
                    job_id=sick_job.id,
                    xero_pay_item_id=ordinary.id,
                ),
            ],
            actor=superuser,
        )

    annual.refresh_from_db()
    assert annual.display_name == "Annual Leave"
    assert annual.job_id == job.id


def test_two_leave_types_can_swap_their_jobs_in_one_save(
    company: Company, job: Job, superuser: Staff
) -> None:
    """LeaveType.job is a OneToOne, so a swap is only expressible in one transaction."""
    annual = configure_type(
        code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
    )
    sick_job = make_job(company, superuser, name="Sick Leave Job")
    sick = configure_type(
        code=LeaveType.Code.SICK, name="Sick Leave", job=sick_job, superuser=superuser
    )

    leave_settings.update_leave_types(
        updates=[
            leave_settings.LeaveTypeUpdateData(
                code=LeaveType.Code.ANNUAL,
                display_name="Annual Leave",
                job_id=sick_job.id,
                xero_pay_item_id=sick_job.default_xero_pay_item_id,
            ),
            leave_settings.LeaveTypeUpdateData(
                code=LeaveType.Code.SICK,
                display_name="Sick Leave",
                job_id=job.id,
                xero_pay_item_id=job.default_xero_pay_item_id,
            ),
        ],
        actor=superuser,
    )

    annual.refresh_from_db()
    sick.refresh_from_db()
    assert annual.job_id == sick_job.id
    assert sick.job_id == job.id


def test_a_job_held_by_an_untouched_leave_type_is_refused_by_name(
    company: Company, job: Job, superuser: Staff
) -> None:
    configure_type(code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser)
    sick_job = make_job(company, superuser, name="Sick Leave Job")
    configure_type(code=LeaveType.Code.SICK, name="Sick Leave", job=sick_job, superuser=superuser)

    with pytest.raises(ValidationError, match="Sick Leave already uses that Docketworks job"):
        leave_settings.update_leave_types(
            updates=[
                leave_settings.LeaveTypeUpdateData(
                    code=LeaveType.Code.ANNUAL,
                    display_name="Annual Leave",
                    job_id=sick_job.id,
                    xero_pay_item_id=sick_job.default_xero_pay_item_id,
                )
            ],
            actor=superuser,
        )


def test_a_duplicated_code_in_one_save_is_refused(job: Job, superuser: Staff) -> None:
    annual = configure_type(
        code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
    )

    with pytest.raises(ValidationError, match="once per request"):
        leave_settings.update_leave_types(
            updates=[update_row(annual), update_row(annual, name="Twice")],
            actor=superuser,
        )


def test_a_public_holiday_edit_saves_beside_other_rows_carrying_no_pay_item(
    company: Company, job: Job, superuser: Staff
) -> None:
    """The xero_computed surface has no Xero item, so null is its finished state.

    Fable: The settings page saves every dirty row in one atomic batch, so a
    public-holiday rename that could not be expressed on the wire did not just
    fail its own row — it rolled back every edit saved beside it.
    """
    annual = configure_type(
        code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
    )
    ph_job = make_job(company, superuser, name="Public Holiday Job")
    public_holiday = configure_type(
        code=LeaveType.Code.PUBLIC_HOLIDAY,
        name="Public Holiday",
        job=ph_job,
        superuser=superuser,
        uses_leave_api=False,
    )

    leave_settings.update_leave_types(
        updates=[
            update_row(annual, name="Renamed Annual"),
            leave_settings.LeaveTypeUpdateData(
                code=LeaveType.Code.PUBLIC_HOLIDAY,
                display_name="Stat Day",
                job_id=ph_job.id,
                xero_pay_item_id=None,
            ),
        ],
        actor=superuser,
    )

    annual.refresh_from_db()
    public_holiday.refresh_from_db()
    assert annual.display_name == "Renamed Annual"
    assert public_holiday.display_name == "Stat Day"


def test_a_pay_item_on_the_public_holiday_row_is_refused(
    company: Company, superuser: Staff
) -> None:
    """Naming a pay item here would post the day twice: Xero computes its own."""
    ph_job = make_job(company, superuser, name="Public Holiday Job")
    configure_type(
        code=LeaveType.Code.PUBLIC_HOLIDAY,
        name="Public Holiday",
        job=ph_job,
        superuser=superuser,
        uses_leave_api=False,
    )

    with pytest.raises(ValidationError, match="takes no Xero payroll item"):
        leave_settings.update_leave_types(
            updates=[
                leave_settings.LeaveTypeUpdateData(
                    code=LeaveType.Code.PUBLIC_HOLIDAY,
                    display_name="Public Holiday",
                    job_id=ph_job.id,
                    xero_pay_item_id=ph_job.default_xero_pay_item_id,
                )
            ],
            actor=superuser,
        )


def test_a_leave_api_row_with_no_pay_item_is_refused(job: Job, superuser: Staff) -> None:
    """Pairs the public-holiday rule with its converse: a surface that posts needs its item."""
    annual = configure_type(
        code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
    )
    assert annual.job is not None

    with pytest.raises(ValidationError, match="requires a Xero leave type"):
        leave_settings.update_leave_types(
            updates=[
                leave_settings.LeaveTypeUpdateData(
                    code=LeaveType.Code.ANNUAL,
                    display_name="Annual Leave",
                    job_id=annual.job.id,
                    xero_pay_item_id=None,
                )
            ],
            actor=superuser,
        )


def test_the_public_holiday_row_reads_with_no_pay_item_and_only_needs_a_job(
    company: Company, superuser: Staff
) -> None:
    """The read side must not leak the job's inert NOT NULL default pay item.

    Fable: Serving it was what made the page round-trip a value the update
    contract then refused; and demanding pay-item validity for a surface that
    never consults one could report a bookable category as unconfigured.
    """
    ph_job = make_job(company, superuser, name="Public Holiday Job")
    configure_type(
        code=LeaveType.Code.PUBLIC_HOLIDAY,
        name="Public Holiday",
        job=ph_job,
        superuser=superuser,
        uses_leave_api=False,
    )

    row = leave_settings.leave_type_data(
        LeaveType.objects.select_related("job__default_xero_pay_item").get(
            code=LeaveType.Code.PUBLIC_HOLIDAY
        )
    )

    assert row["xero_pay_item_id"] is None
    assert row["xero_pay_item_name"] is None
    assert row["configured"] is True


@pytest.mark.usefixtures("worker")
def test_an_office_closure_writes_no_xero_pay_item_so_the_day_is_paid_once(
    job: Job, superuser: Staff
) -> None:
    """The office-closure path is where public-holiday lines are actually created.

    Opus: Xero Payroll NZ computes public-holiday pay itself from the employee's
    working pattern and offers no endpoint to suppress it, so a line naming a
    Xero pay item is posted to the Timesheets API ON TOP of what Xero already
    pays. This path copied the job's default — "Ordinary Time" — onto every
    line it created, which is the write that paid the day twice. Asserting on
    the created CostLine rather than on the classifier, because the classifier
    was already right while this path went on producing the wrong rows.
    """
    configure_type(
        code=LeaveType.Code.PUBLIC_HOLIDAY,
        name="Public Holiday",
        job=job,
        superuser=superuser,
        uses_leave_api=False,
    )

    leave_service.create_office_closure(
        start_date=MONDAY,
        end_date=MONDAY,
        note="Office closed",
        actor=superuser,
    )

    lines = CostLine.objects.filter(cost_set__job=job, kind="time", cost_set__kind="actual")
    assert lines.exists(), "the closure must still record the hours"
    assert not lines.exclude(xero_pay_item__isnull=True).exists(), (
        "a public-holiday line naming a Xero pay item is posted on top of Xero's own line"
    )


def test_office_closure_creates_one_public_holiday_request_per_payroll_staff(
    worker: Staff, other_worker: Staff, job: Job, superuser: Staff
) -> None:
    configure_type(
        code=LeaveType.Code.PUBLIC_HOLIDAY,
        name="Public Holiday",
        job=job,
        superuser=superuser,
        uses_leave_api=False,
    )

    result = leave_service.create_office_closure(
        start_date=MONDAY,
        end_date=MONDAY,
        note="Office closed",
        actor=superuser,
    )

    assert {row["staff_id"] for row in result["requests"]} == {
        str(worker.id),
        str(other_worker.id),
    }
    assert {row.source for row in LeaveRequest.objects.all()} == {
        LeaveRequest.Source.OFFICE_CLOSURE
    }
    assert LeaveDay.objects.count() == 2
    assert CostLine.objects.filter(managed_by="leave").count() == 2


class TestRequestedDayRules:
    """What a leave request refuses, and what each refusal protects."""

    def test_hours_beyond_the_days_roster_are_refused(
        self, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """Payroll integrity: an 8-hour day cannot be paid 12 hours of leave."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )

        with pytest.raises(ValidationError, match="no more than the scheduled"):
            leave_service.create_leave_request(
                staff_id=worker.id,
                leave_type_code=LeaveType.Code.ANNUAL,
                start_date=MONDAY,
                end_date=MONDAY,
                note=None,
                requested_days=requested((MONDAY, "12")),
                actor=superuser,
            )
        assert not LeaveRequest.objects.exists()

    def test_the_same_date_may_not_be_supplied_twice(
        self, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """Otherwise one day is paid twice out of a single request."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )

        with pytest.raises(ValidationError, match="only once"):
            leave_service.create_leave_request(
                staff_id=worker.id,
                leave_type_code=LeaveType.Code.ANNUAL,
                start_date=MONDAY,
                end_date=TUESDAY,
                note=None,
                requested_days=requested((MONDAY, "4"), (MONDAY, "4")),
                actor=superuser,
            )
        assert not LeaveRequest.objects.exists()

    def test_a_date_outside_the_requested_range_is_refused(
        self, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """A day the operator never previewed must not be paid."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )

        with pytest.raises(ValidationError, match="outside the requested date range"):
            leave_service.create_leave_request(
                staff_id=worker.id,
                leave_type_code=LeaveType.Code.ANNUAL,
                start_date=MONDAY,
                end_date=MONDAY,
                note=None,
                requested_days=requested((TUESDAY, "8")),
                actor=superuser,
            )
        assert not LeaveRequest.objects.exists()

    def test_a_request_whose_every_day_conflicts_saves_nothing(
        self, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """Refused outright rather than persisted as a request with no days."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )
        make_time_line(job, worker, accounting_date=MONDAY)

        with pytest.raises(ValidationError, match="No available leave days remain"):
            leave_service.create_leave_request(
                staff_id=worker.id,
                leave_type_code=LeaveType.Code.ANNUAL,
                start_date=MONDAY,
                end_date=MONDAY,
                note=None,
                requested_days=requested((MONDAY, "8")),
                actor=superuser,
            )
        assert not LeaveRequest.objects.exists()
        assert not LeaveDay.objects.exists()

    def test_a_reversed_date_range_is_refused(self, worker: Staff) -> None:
        """An empty range would otherwise preview as simply having no days."""
        with pytest.raises(ValidationError, match="End date must be on or after start date"):
            leave_service.preview_leave(staff=worker, start_date=TUESDAY, end_date=MONDAY)


class TestPreviewReasons:
    """Why a day is unavailable, in the words the preview table shows."""

    def test_a_day_before_employment_started_is_outside_employment_dates(
        self, superuser: Staff
    ) -> None:
        del superuser
        starter = make_staff("leave-starter@example.com", first_name="Sam", last_name="Starter")
        # Set after creation: make_staff pins employment_start_date itself.
        starter.employment_start_date = TUESDAY
        starter.save(update_fields=["employment_start_date"])

        preview = leave_service.preview_leave(staff=starter, start_date=MONDAY, end_date=TUESDAY)

        reasons = {row["date"]: row["reason"] for row in preview["days"]}
        assert reasons[MONDAY] == "Outside employment dates"
        assert reasons[TUESDAY] is None

    def test_a_day_on_or_after_a_recorded_departure_is_outside_employment_dates(self) -> None:
        """The departure this branch stopped the employee sync from erasing."""
        leaver = make_staff(
            "leave-leaver@example.com",
            first_name="Lee",
            last_name="Leaver",
            date_left=TUESDAY,
        )

        preview = leave_service.preview_leave(staff=leaver, start_date=MONDAY, end_date=TUESDAY)

        reasons = {row["date"]: row["reason"] for row in preview["days"]}
        assert reasons[MONDAY] is None
        assert reasons[TUESDAY] == "Outside employment dates"

    def test_an_unrostered_day_is_not_a_scheduled_working_day(self, worker: Staff) -> None:
        saturday = MONDAY + timedelta(days=5)

        preview = leave_service.preview_leave(staff=worker, start_date=saturday, end_date=saturday)

        [row] = preview["days"]
        assert row["reason"] == "Not a scheduled working day"
        assert row["scheduled_hours"] == Decimal("0")
        assert row["available"] is False


class TestLeaveBalance:
    """Each refusal is a distinct diagnosis the operator reads in the dialog."""

    def _provider(self, *balances: PayrollLeaveBalance) -> SimpleNamespace:
        return SimpleNamespace(get_payroll_leave_balances=lambda _employee_id: list(balances))

    def test_staff_with_no_payroll_link_is_named(self, job: Job, superuser: Staff) -> None:
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )
        unlinked = make_staff("leave-unlinked@example.com", xero_user_id="")

        with pytest.raises(ValidationError, match="is not linked to payroll"):
            leave_service.get_leave_balance(staff=unlinked, leave_type_code=LeaveType.Code.ANNUAL)

    def test_an_unmapped_leave_type_is_refused_before_xero_is_called(self, worker: Staff) -> None:
        """The seeded row exists but has no job, so there is nothing to ask about."""
        with pytest.raises(ValidationError, match="is not fully configured"):
            leave_service.get_leave_balance(staff=worker, leave_type_code=LeaveType.Code.ANNUAL)

    def test_a_type_paid_as_an_earnings_rate_has_no_balance(
        self, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """Public Holiday posts through earnings, not the Leave API — it has no balance."""
        configure_type(
            code=LeaveType.Code.PUBLIC_HOLIDAY,
            name="Public Holiday",
            job=job,
            superuser=superuser,
            uses_leave_api=False,
        )

        with pytest.raises(ValidationError, match="does not have a leave balance"):
            leave_service.get_leave_balance(
                staff=worker, leave_type_code=LeaveType.Code.PUBLIC_HOLIDAY
            )

    def test_a_balance_xero_does_not_hold_is_reported_rather_than_read_as_zero(
        self, monkeypatch: pytest.MonkeyPatch, worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """The post-incomplete-employee-sync case: absent is not the same as nil."""
        configure_type(
            code=LeaveType.Code.ANNUAL, name="Annual Leave", job=job, superuser=superuser
        )
        provider = self._provider()
        monkeypatch.setattr(leave_service, "get_provider", lambda: provider)

        with pytest.raises(ValidationError, match="Xero returned no Annual Leave balance"):
            leave_service.get_leave_balance(staff=worker, leave_type_code=LeaveType.Code.ANNUAL)


class TestOfficeClosure:
    """A firm-wide write, so what it skips and what it refuses both matter."""

    def test_preview_counts_only_the_staff_a_closure_could_actually_pay(
        self, worker: Staff, other_worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """available_staff and available_hours are what the operator commits on."""
        configure_type(
            code=LeaveType.Code.PUBLIC_HOLIDAY,
            name="Public Holiday",
            job=job,
            superuser=superuser,
            uses_leave_api=False,
        )
        make_time_line(job, other_worker, accounting_date=MONDAY)

        preview = leave_service.preview_office_closure(start_date=MONDAY, end_date=MONDAY)

        assert preview["available_staff"] == 1
        assert preview["available_hours"] == Decimal("8")
        by_staff = {row["staff_id"]: row for row in preview["staff"]}
        assert by_staff[str(worker.id)]["available_hours"] == Decimal("8")
        assert by_staff[str(other_worker.id)]["available_hours"] == Decimal("0")

    def test_a_staff_member_with_no_available_day_is_skipped_not_given_an_empty_request(
        self, worker: Staff, other_worker: Staff, job: Job, superuser: Staff
    ) -> None:
        configure_type(
            code=LeaveType.Code.PUBLIC_HOLIDAY,
            name="Public Holiday",
            job=job,
            superuser=superuser,
            uses_leave_api=False,
        )
        make_time_line(job, other_worker, accounting_date=MONDAY)

        result = leave_service.create_office_closure(
            start_date=MONDAY, end_date=MONDAY, note=None, actor=superuser
        )

        assert {row["staff_id"] for row in result["requests"]} == {str(worker.id)}
        assert not LeaveRequest.objects.filter(staff=other_worker).exists()

    def test_a_closure_nobody_can_take_is_refused_outright(
        self, worker: Staff, other_worker: Staff, job: Job, superuser: Staff
    ) -> None:
        """A Saturday is rostered for nobody: the batch fails rather than writing nothing."""
        configure_type(
            code=LeaveType.Code.PUBLIC_HOLIDAY,
            name="Public Holiday",
            job=job,
            superuser=superuser,
            uses_leave_api=False,
        )
        saturday = MONDAY + timedelta(days=5)
        del worker, other_worker

        with pytest.raises(ValidationError, match="No available office-closure days remain"):
            leave_service.create_office_closure(
                start_date=saturday, end_date=saturday, note=None, actor=superuser
            )
        assert not LeaveRequest.objects.exists()


class TestLeaveMappingRules:
    """What a leave type may be pointed at, and what it may never be pointed at."""

    def _pay_item_id(self, **overrides: object) -> UUID:
        """A pay item built through get_model, so this app never imports apps.xero."""
        defaults = CompanyDefaults.get_solo()
        pay_item_model = django_apps.get_model("xero", "XeroPayItem")
        fields: dict[str, object] = {
            "name": "Spare Leave",
            "uses_leave_api": True,
            "xero_id": "xero-spare",
            "xero_tenant_id": defaults.xero_tenant_id,
            "multiplier": None,
        }
        fields.update(overrides)
        created: Model = pay_item_model.objects.create(**fields)
        return UUID(str(created.pk))

    def _update(self, job: Job, pay_item_id: UUID) -> leave_settings.LeaveTypeUpdateData:
        return leave_settings.LeaveTypeUpdateData(
            code=LeaveType.Code.ANNUAL,
            display_name="Annual Leave",
            job_id=job.id,
            xero_pay_item_id=pay_item_id,
        )

    def test_a_live_customer_job_may_not_back_a_leave_type(
        self, company: Company, superuser: Staff
    ) -> None:
        """Otherwise every leave hour lands on that customer's actual costs."""
        customer_job = make_job(company, superuser, name="Real Customer Work")
        pay_item_id = self._pay_item_id()

        with pytest.raises(ValidationError, match="must use a special Docketworks job"):
            leave_settings.update_leave_types(
                updates=[self._update(customer_job, pay_item_id)], actor=superuser
            )

    def test_a_pay_item_never_synced_to_xero_is_refused(self, job: Job, superuser: Staff) -> None:
        job.status = "special"
        job.save(staff=superuser, update_fields=["status", "updated_at"])
        # NULL, not "": a not-blank CHECK constraint makes the empty string
        # impossible, so an unsynced row is one that has no id at all.
        unsynced_id = self._pay_item_id(xero_id=None)

        with pytest.raises(ValidationError, match="not linked to the current organisation"):
            leave_settings.update_leave_types(
                updates=[self._update(job, unsynced_id)], actor=superuser
            )

    def test_a_pay_item_from_another_xero_organisation_is_refused(
        self, job: Job, superuser: Staff
    ) -> None:
        """The defence against posting payroll into a stale tenant after a reconnection."""
        job.status = "special"
        job.save(staff=superuser, update_fields=["status", "updated_at"])
        foreign_id = self._pay_item_id(xero_tenant_id=str(uuid4()))

        with pytest.raises(ValidationError, match="belongs to a different organisation"):
            leave_settings.update_leave_types(
                updates=[self._update(job, foreign_id)], actor=superuser
            )

    def test_booking_against_an_unmapped_type_is_refused(self, worker: Staff) -> None:
        """The seeded row exists with no job, so it is not bookable."""
        with pytest.raises(ValidationError, match="Annual Leave is not fully configured"):
            leave_service.create_leave_request(
                staff_id=worker.id,
                leave_type_code=LeaveType.Code.ANNUAL,
                start_date=MONDAY,
                end_date=MONDAY,
                note=None,
                requested_days=requested((MONDAY, "8")),
                actor=worker,
            )


class TestEmployeeLeaveMappings:
    """The employee sync's precondition.

    Covered only by the integration suite until now, which `uv run pytest`
    deselects — but these are pure local-DB rules with no Xero call, so nothing
    was gating the commit that broke them.
    """

    def _configure_all(self, company: Company, superuser: Staff) -> None:
        for code, name in (
            (LeaveType.Code.ANNUAL, "Annual Leave"),
            (LeaveType.Code.SICK, "Sick Leave"),
            (LeaveType.Code.UNPAID, "Unpaid Leave"),
            (LeaveType.Code.BEREAVEMENT, "Bereavement Leave"),
        ):
            configure_type(
                code=code,
                name=name,
                job=make_job(company, superuser, name=f"{name} Job"),
                superuser=superuser,
            )

    def test_all_four_leave_api_types_map_to_their_xero_ids(
        self, company: Company, superuser: Staff
    ) -> None:
        self._configure_all(company, superuser)

        mappings = leave_settings.employee_leave_mappings()

        assert {row.code for row in mappings} == {
            LeaveType.Code.ANNUAL,
            LeaveType.Code.SICK,
            LeaveType.Code.UNPAID,
            LeaveType.Code.BEREAVEMENT,
        }
        # Public Holiday is excluded: it posts through earnings, not the Leave API.
        assert LeaveType.Code.PUBLIC_HOLIDAY not in {row.code for row in mappings}
        # Only annual and sick accrue a standard entitlement in Xero.
        assert {row.code for row in mappings if row.standard_entitlement} == {
            LeaveType.Code.ANNUAL,
            LeaveType.Code.SICK,
        }

    def test_an_unmapped_type_stops_the_sync_by_name(
        self, company: Company, superuser: Staff
    ) -> None:
        """Naming the type is the difference between a fixable message and a hunt."""
        self._configure_all(company, superuser)
        LeaveType.objects.filter(code=LeaveType.Code.SICK).update(job=None)

        with pytest.raises(ValueError, match="Sick Leave is not linked to a Xero leave type"):
            leave_settings.employee_leave_mappings()
