"""Every timesheet entry write leaves a TimesheetEvent, whoever makes it.

Workshop staff enter their own time through the entry endpoint and the office
anyone's, naming ``staff_id``; the job's cost grid still deletes an entry
through the generic cost-line service. Each test names the write site whose
record call a plausible edit would drop.
"""

from datetime import date, time, timedelta
from decimal import Decimal
from unittest import mock
from uuid import UUID, uuid4

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.enums import CostLineOwner
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services import job_service
from apps.job.services.job_service import CostLineWriteData
from apps.timesheet.models import TimesheetEvent
from apps.timesheet.services import attendance, workshop_timesheet_service
from apps.timesheet.tests import test_approval
from apps.timesheet.tests.conftest import WEEK_START, authenticated_client

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

URL = "/api/job/workshop/timesheets/"
ENTRY_DATE: date = WEEK_START

#: The one General work fixture (ADR 0039), registered in this module by name.
general_work = test_approval.general_work


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

    def test_editing_hours_records_the_hours_and_the_finish_they_move(
        self, worker_client: Client, job: Job
    ) -> None:
        line_id = _workshop_create(worker_client, job)

        response = worker_client.patch(
            URL,
            data={"entry_id": line_id, "hours": "6.00"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        *_, updated = _events(line_id)
        assert updated.event_type == "entry_updated"
        # The finish is the hours' picture, so it moves with them and is recorded too.
        assert {
            change["field_name"]: change["new_value"] for change in updated.detail["changes"]
        } == {
            "Hours": "6.000",
            "End": "14:00:00",
        }

    def test_editing_only_the_times_records_the_change(
        self, worker_client: Client, job: Job
    ) -> None:
        """The snapshot carries start and end: a time-only edit is not a blank "Entry updated"."""
        # Both spans hold no break, so the times stand as typed.
        line_id = _workshop_create(
            worker_client, job, start_time="09:00:00", end_time="10:00:00", hours="1.00"
        )

        response = worker_client.patch(
            URL,
            data={"entry_id": line_id, "start_time": "10:00:00", "end_time": "11:00:00"},
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        *_, updated = _events(line_id)
        assert updated.detail["changes"] == [
            {"field_name": "Start", "old_value": "09:00:00", "new_value": "10:00:00"},
            {"field_name": "End", "old_value": "10:00:00", "new_value": "11:00:00"},
        ]
        assert updated.description == (
            "Start changed from '09:00:00' to '10:00:00'. End changed from '10:00:00' to '11:00:00'"
        )

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
    """The office enters time through the entry endpoint naming ``staff_id``; the job's cost
    grid deletes it through ``job_service.delete_cost_line``."""

    def test_creating_records_entry_created_by_the_office_actor(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        line_id = _workshop_create(
            authenticated_client(office_staff), job, staff_id=str(worker.id), hours="2.00"
        )

        (event,) = _events(line_id)
        assert event.event_type == "entry_created"
        assert event.staff == office_staff
        assert event.worker == worker
        assert event.delta_after is not None
        # Entering is not approving, even by the office (owner, 2026-10-26).
        assert event.delta_after["approved"] is False

    def test_editing_records_entry_updated(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        office = authenticated_client(office_staff)
        line_id = _workshop_create(office, job, staff_id=str(worker.id), hours="2.00")

        response = office.patch(
            URL, data={"entry_id": line_id, "hours": "3.00"}, content_type="application/json"
        )

        assert response.status_code == 200, response.content
        *_, updated = _events(line_id)
        assert updated.event_type == "entry_updated"
        assert updated.staff == office_staff
        # The 2h were placed from 07:00, around the 08:30 break; the finish follows the hours.
        assert updated.description == (
            "End changed from '09:15:00' to '10:15:00'. Hours changed from '2.000' to '3.000'"
        )

    def test_deleting_records_entry_deleted(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        """Guards job_service.delete_cost_line handing an entry to the entry writer."""
        line_id = _workshop_create(authenticated_client(office_staff), job, staff_id=str(worker.id))

        job_service.delete_cost_line(CostLine.objects.get(id=line_id), office_staff)

        *_, deleted = _events(line_id)
        assert deleted.event_type == "entry_deleted"
        assert deleted.delta_after is None

    def test_a_write_that_carries_no_location_is_untrusted_unless_the_office_made_it(
        self, worker_client: Client, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        """A save with no position: a worker saving from home must not read as here."""
        company = CompanyDefaults.get_solo()
        company.latitude = Decimal("-36.850000")
        company.longitude = Decimal("174.760000")
        company.save(update_fields=["latitude", "longitude"])
        theirs = _workshop_create(worker_client, job)
        worker_client.patch(
            URL, data={"entry_id": theirs, "hours": "3.00"}, content_type="application/json"
        )
        office = _workshop_create(authenticated_client(office_staff), job, staff_id=str(worker.id))

        assert [event.trusted for event in _events(theirs)] == [False, False]
        assert [event.trusted for event in _events(office)] == [True]

    @pytest.mark.usefixtures("break_job")
    def test_lines_nobody_typed_are_trusted_wherever_he_was(
        self, job: Job, worker: Staff, general_work: Job
    ) -> None:
        """Breaks and General work are made for him, not entered from anywhere.

        Guards workshop_timesheet_service._save_entry and _delete_line: a line
        with a source is trusted on create, and the General work rebuild's
        delete is trusted, while his own entry from no location is not.
        """
        company = CompanyDefaults.get_solo()
        company.latitude = Decimal("-36.850000")
        company.longitude = Decimal("174.760000")
        company.save(update_fields=["latitude", "longitude"])
        attendance.set_clock_times(worker, ENTRY_DATE, time(7, 0), time(15, 0), worker)
        workshop_timesheet_service.fill_with_general_work(worker, ENTRY_DATE, worker)
        filled = set(
            CostLine.objects.filter(staff=worker, cost_set__job=general_work).values_list(
                "id", flat=True
            )
        )

        entry = workshop_timesheet_service.create_entry(
            worker,
            worker,
            {"job_id": job.id, "accounting_date": ENTRY_DATE, "hours": Decimal("1")},
        )

        made_for_him = TimesheetEvent.objects.filter(
            worker=worker, event_type="entry_created"
        ).exclude(cost_line_id=entry["id"])
        assert made_for_him.count() > len(filled)
        assert all(event.trusted for event in made_for_him)
        rebuilt = TimesheetEvent.objects.filter(
            event_type="entry_deleted", cost_line_id__in=list(filled)
        )
        assert rebuilt.count() == len(filled)
        assert all(event.trusted for event in rebuilt)
        assert [event.trusted for event in _events(entry["id"])] == [False]

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
        job_service.update_cost_line(line, {"quantity": Decimal("2.000")})
        job_service.delete_cost_line(line, office_staff)

        assert _events(line.id) == []

    def test_a_leave_created_line_is_audited_like_any_entry(
        self, job: Job, worker: Staff, office_staff: Staff
    ) -> None:
        """A line the Leave screen created is an ordinary entry once it exists (owner ruling)."""
        entry = workshop_timesheet_service.create_entry(
            office_staff,
            worker,
            {"job_id": job.id, "accounting_date": ENTRY_DATE, "hours": Decimal("8.00")},
            managed_by=CostLineOwner.LEAVE,
        )

        (event,) = _events(UUID(entry["id"]))
        assert event.event_type == "entry_created"
        assert event.worker == worker


HISTORY_URL = "/api/job/timesheet/entries/history/"


def _history_url(staff: Staff, day: date = ENTRY_DATE) -> str:
    return f"{HISTORY_URL}?staff_id={staff.id}&date={day.isoformat()}"


class TestHistoryEndpoint:
    """``job_timesheet_entries_history_retrieve``: one worker-day, newest first, deletes too."""

    def test_lists_the_days_events_newest_first_including_a_deleted_entry(
        self, worker_client: Client, manage_client: Client, job: Job, worker: Staff
    ) -> None:
        kept = _workshop_create(worker_client, job)
        gone = _workshop_create(worker_client, job, hours="1.00")
        assert worker_client.delete(f"{URL}?entry_id={gone}").status_code == 204

        response = manage_client.get(_history_url(worker))

        assert response.status_code == 200, response.content
        body = response.json()
        assert [event["event_type"] for event in body] == [
            "entry_deleted",
            "entry_created",
            "entry_created",
        ]
        deleted = body[0]
        assert deleted["before"]["hours"] == "1.000"
        assert deleted["after"] is None
        assert deleted["description"] == "Entry deleted"
        assert deleted["staff_name"] == worker.get_display_full_name()
        assert body[2]["after"]["job"] == f"#{job.job_number}"
        assert sum(1 for event in body if event["after"] is not None) == 2
        assert TimesheetEvent.objects.filter(cost_line_id=kept).count() == 1

    def test_another_day_is_not_listed(
        self, worker_client: Client, manage_client: Client, job: Job, worker: Staff
    ) -> None:
        _workshop_create(worker_client, job)

        response = manage_client.get(_history_url(worker, ENTRY_DATE + timedelta(days=1)))

        assert response.status_code == 200
        assert response.json() == []

    def test_management_auth_like_the_entries_read(
        self, worker_client: Client, worker: Staff
    ) -> None:
        # The snapshots carry the wage rate; the entries read gates on the same rule.
        assert worker_client.get(_history_url(worker)).status_code == 403
        assert Client().get(_history_url(worker)).status_code == 401

    def test_unknown_staff_is_404(self, manage_client: Client) -> None:
        response = manage_client.get(f"{HISTORY_URL}?staff_id={uuid4()}&date={ENTRY_DATE}")
        assert response.status_code == 404
