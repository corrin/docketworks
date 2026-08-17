"""Leave requests as first-class records with CostLine payroll projections."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounting.types import PayrollLeaveBalance
from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services import job_service
from apps.timesheet.models import LeaveDay, LeaveRequest, LeaveType
from apps.timesheet.services import leave_service, leave_settings
from apps.timesheet.tests.conftest import make_time_line

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
        leave_settings.update_leave_type(
            code=LeaveType.Code.ANNUAL,
            display_name="Holiday",
            job_id=job.id,
            xero_pay_item_id=ordinary.id,
            actor=superuser,
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
