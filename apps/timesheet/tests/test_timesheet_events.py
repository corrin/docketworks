"""Every timesheet entry write leaves a TimesheetEvent, on both paths.

The office grid edits any staff member's time through the generic cost-line
services; workshop staff edit their own through the self-service PATCH. Each
test names the write site whose record call a plausible edit would drop.
"""

from datetime import date
from decimal import Decimal
from unittest import mock
from uuid import UUID

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services import job_service
from apps.job.services.job_service import CostLineWriteData
from apps.timesheet.models import TimesheetEvent
from apps.timesheet.tests.conftest import WEEK_START

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

URL = "/api/job/workshop/timesheets/"
ENTRY_DATE: date = WEEK_START


def _events(line_id: UUID | str) -> list[TimesheetEvent]:
    return list(TimesheetEvent.objects.filter(cost_line_id=line_id).order_by("timestamp"))


def _workshop_create(client: Client, job: Job, **overrides: object) -> str:
    payload: dict[str, object] = {
        "job_id": str(job.id),
        "accounting_date": ENTRY_DATE.isoformat(),
        "hours": "4.00",
        "description": "Fabrication",
    }
    payload.update(overrides)
    response = client.post(URL, data=payload, content_type="application/json")
    assert response.status_code == 201, response.content
    return str(response.json()["id"])


def _office_data(worker: Staff, **meta: object) -> CostLineWriteData:
    return {
        "kind": "time",
        "desc": "Timesheet entry",
        "quantity": Decimal("2.000"),
        "unit_cost": Decimal("0.00"),
        "unit_rev": Decimal("0.00"),
        "accounting_date": ENTRY_DATE,
        "ext_refs": {},
        "meta": {
            "created_from_timesheet": True,
            "staff_id": str(worker.id),
            "wage_rate_multiplier": 1.0,
            **meta,
        },
    }


class TestWorkshopPath:
    """``workshop_timesheet_service``: create_entry, update_entry, delete_entry."""

    def test_creating_records_entry_created_with_the_entry_as_after(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        line_id = _workshop_create(worker_client, job)

        (event,) = _events(line_id)
        assert event.event_type == "entry_created"
        assert event.staff == worker
        assert event.worker == worker
        assert event.accounting_date == ENTRY_DATE
        assert event.delta_before is None
        assert event.delta_after is not None
        assert event.delta_after["hours"] == "4.000"
        assert event.delta_after["job"] == f"#{job.job_number}"
        assert event.description == "Entry created"

    def test_editing_hours_records_the_one_change(self, worker_client: Client, job: Job) -> None:
        line_id = _workshop_create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": line_id, "hours": "6.00"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        *_, updated = _events(line_id)
        assert updated.event_type == "entry_updated"
        assert updated.detail["changes"] == [
            {"field_name": "Hours", "old_value": "4.000", "new_value": "6.000"}
        ]
        assert updated.description == "Hours changed from '4.000' to '6.000'"

    def test_moving_records_entry_moved_naming_both_jobs(
        self, worker_client: Client, job: Job, company: Company, superuser: Staff
    ) -> None:
        other = make_job(company, superuser, name="Other Job")
        other.labour_rates.update(charge_out_rate=Decimal("200.00"))
        line_id = _workshop_create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": line_id, "job_id": str(other.id)},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        *_, moved = _events(line_id)
        assert moved.event_type == "entry_moved"
        assert moved.description.startswith(f"Moved from #{job.job_number} to #{other.job_number}")
        assert "Charge-out $/h changed from '120.00' to '200.00'" in moved.description

    def test_deleting_records_entry_deleted_and_the_event_outlives_the_line(
        self, worker_client: Client, job: Job, worker: Staff
    ) -> None:
        line_id = _workshop_create(worker_client, job)

        response = worker_client.delete(f"{URL}?entry_id={line_id}")

        assert response.status_code == 204, response.content
        assert not CostLine.objects.filter(id=line_id).exists()
        *_, deleted = _events(line_id)
        assert deleted.event_type == "entry_deleted"
        assert deleted.worker == worker
        assert deleted.delta_after is None
        assert deleted.delta_before is not None
        assert deleted.delta_before["hours"] == "4.000"

    def test_the_event_rolls_back_with_a_write_that_fails(
        self, worker_client: Client, job: Job
    ) -> None:
        """Recording happens inside the write's transaction, not beside it."""
        line_id = _workshop_create(worker_client, job)

        with mock.patch.object(CostLine, "delete", side_effect=RuntimeError("disk full")):
            response = worker_client.delete(f"{URL}?entry_id={line_id}")

        assert response.status_code == 500
        assert CostLine.objects.filter(id=line_id).exists()
        assert [event.event_type for event in _events(line_id)] == ["entry_created"]


class TestOfficePath:
    """``job_service``: create_cost_line, update_cost_line, delete_cost_line."""

    def test_creating_records_entry_created_by_the_office_actor(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        line = job_service.create_cost_line(job, "actual", _office_data(worker), office_staff)

        (event,) = _events(line.id)
        assert event.event_type == "entry_created"
        assert event.staff == office_staff
        assert event.worker == worker
        assert event.delta_after is not None
        assert event.delta_after["approved"] is True

    def test_editing_records_entry_updated(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        line = job_service.create_cost_line(job, "actual", _office_data(worker), office_staff)

        job_service.update_cost_line(line, {"quantity": Decimal("3.000")}, office_staff)

        *_, updated = _events(line.id)
        assert updated.event_type == "entry_updated"
        assert updated.staff == office_staff
        assert updated.description == "Hours changed from '2.000' to '3.000'"

    def test_deleting_records_entry_deleted(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        line = job_service.create_cost_line(job, "actual", _office_data(worker), office_staff)

        job_service.delete_cost_line(line, office_staff)

        *_, deleted = _events(line.id)
        assert deleted.event_type == "entry_deleted"
        assert deleted.delta_after is None

    def test_a_material_line_records_nothing(self, job: Job, office_staff: Staff) -> None:
        data: CostLineWriteData = {
            "kind": "material",
            "desc": "Steel",
            "quantity": Decimal("1.000"),
            "unit_cost": Decimal("10.00"),
            "unit_rev": Decimal("15.00"),
            "accounting_date": ENTRY_DATE,
            "ext_refs": {},
            "meta": {},
        }
        line = job_service.create_cost_line(job, "actual", data, office_staff)
        job_service.update_cost_line(line, {"quantity": Decimal("2.000")}, office_staff)
        job_service.delete_cost_line(line, office_staff)

        assert _events(line.id) == []

    def test_a_leave_managed_line_records_nothing(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        """Leave lines are written in batches by a leave request, which names its author."""
        data = _office_data(worker)
        data["managed_by"] = "leave"

        line = job_service.create_cost_line(job, "actual", data, office_staff)

        assert _events(line.id) == []
