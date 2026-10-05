"""Office approval of worked time: a person's day at once, and what the screen is told."""

from collections.abc import Iterator
from datetime import time, timedelta

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.models import TimesheetEvent
from apps.timesheet.services import approval, attendance
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
    make_leave_job,
    make_staff,
    make_time_line,
)

pytestmark = pytest.mark.django_db

DAY = WEEK_START
APPROVALS_URL = "/api/timesheets/approvals/"
WORKSHOP_DAY_URL = "/api/job/workshop/timesheets/"


def _keys(value: object) -> Iterator[str]:
    """Every key anywhere in a JSON body."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


def _money_keys(body: object) -> set[str]:
    """Keys that would carry a rate, a cost or a revenue figure. Multipliers are not money."""
    return {
        key
        for key in _keys(body)
        if "cost" in key or "revenue" in key or key.startswith("unit_") or key.endswith("_rate")
    }


class TestApproveDay:
    def test_approve_day_approves_every_waiting_line_and_records_each(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        first = make_time_line(job, worker, accounting_date=DAY, hours="3.000", approved=False)
        second = make_time_line(job, worker, accounting_date=DAY, hours="5.000", approved=False)
        tomorrow = make_time_line(
            job, worker, accounting_date=DAY + timedelta(days=1), approved=False
        )
        someone_else = make_time_line(job, other_worker, accounting_date=DAY, approved=False)

        response = authenticated_client(office_staff).post(
            f"{APPROVALS_URL}{worker.id}/{DAY.isoformat()}/approve/"
        )

        assert response.status_code == 200, response.content
        assert response.json() == {"approved_count": 2}
        approved = set(CostLine.objects.filter(approved=True).values_list("id", flat=True))
        assert approved == {first.id, second.id}
        assert not CostLine.objects.filter(id__in=[tomorrow.id, someone_else.id], approved=True)
        events = TimesheetEvent.objects.filter(event_type="entry_approved")
        assert {event.cost_line_id for event in events} == {first.id, second.id}
        assert {event.staff_id for event in events} == {office_staff.id}

    def test_approve_day_skips_leave_lines(
        self, office_staff: Staff, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """Leave is approved when it is made; a managed line is not this screen's to touch."""
        leave_job = make_leave_job(company, superuser, "Annual Leave")
        leave = make_time_line(leave_job, worker, accounting_date=DAY, approved=False)
        CostLine.objects.filter(pk=leave.pk).update(managed_by="leave")

        assert approval.approve_day(worker, DAY, office_staff) == 0

        leave.refresh_from_db()
        assert leave.approved is False

    def test_a_day_with_nothing_waiting_answers_zero(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        make_time_line(job, worker, accounting_date=DAY)

        response = authenticated_client(office_staff).post(
            f"{APPROVALS_URL}{worker.id}/{DAY.isoformat()}/approve/"
        )

        assert response.status_code == 200
        assert response.json() == {"approved_count": 0}

    def test_workshop_staff_cannot_approve(self, worker_client: Client, worker: Staff) -> None:
        response = worker_client.post(f"{APPROVALS_URL}{worker.id}/{DAY.isoformat()}/approve/")

        assert response.status_code == 403


class TestApprovalsRead:
    def test_people_with_time_waiting_come_first_then_nothing_entered(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """The list opens on what needs doing; an empty day is its own state."""
        done = other_worker
        make_time_line(job, done, accounting_date=DAY, hours="8.000")
        make_time_line(job, worker, accounting_date=DAY, hours="5.000")
        make_time_line(job, worker, accounting_date=DAY, hours="3.000", approved=False)
        absent = make_staff("timesheet-absent@example.com", first_name="Abe", last_name="Absent")

        body = (
            authenticated_client(office_staff).get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()
        )

        rows = {row["staff_id"]: row for row in body["staff"]}
        assert [row["staff_id"] for row in body["staff"]] == [
            str(worker.id),
            str(absent.id),
            str(done.id),
        ]
        assert rows[str(worker.id)]["state"] == "waiting"
        assert rows[str(worker.id)]["entered_hours"] == 8.0
        assert rows[str(worker.id)]["waiting_hours"] == 3.0
        assert len(rows[str(worker.id)]["entries"]) == 2
        assert rows[str(absent.id)]["state"] == "nothing_entered"
        assert rows[str(done.id)]["state"] == "nothing_waiting"

    def test_a_waiting_entry_made_late_or_away_marks_the_persons_row(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        """An approved entry's marks are history; only what is waiting flags the row."""
        approved = make_time_line(job, worker, accounting_date=DAY, hours="1.000")
        waiting = make_time_line(job, worker, accounting_date=DAY, hours="2.000", approved=False)
        CostLine.objects.filter(pk=approved.pk).update(remote_entry=True)
        client = authenticated_client(office_staff)

        [row] = [
            row
            for row in client.get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()["staff"]
            if row["staff_id"] == str(worker.id)
        ]
        assert row["remote_entry"] is False

        CostLine.objects.filter(pk=waiting.pk).update(remote_entry=True)
        [row] = [
            row
            for row in client.get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()["staff"]
            if row["staff_id"] == str(worker.id)
        ]
        assert row["remote_entry"] is True
        assert {entry["hours"]: entry["remote_entry"] for entry in row["entries"]} == {
            1.0: True,
            2.0: True,
        }

    def test_each_row_says_whether_the_person_was_here_apart_from_approval(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """Clocked out with nothing entered, and time waiting without a clock-in, are both days."""
        attendance.set_clock_times(worker, DAY, time(6, 30), time(15, 0), worker)
        make_time_line(job, other_worker, accounting_date=DAY, approved=False)

        body = (
            authenticated_client(office_staff).get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()
        )

        rows = {row["staff_id"]: row for row in body["staff"]}
        assert rows[str(worker.id)]["state"] == "nothing_entered"
        assert rows[str(worker.id)]["clock"] == {
            "state": "clocked_out",
            "clock_in": "06:30:00",
            "clock_out": "15:00:00",
            "here_hours": 8.5,
            "sent_late": False,
        }
        assert rows[str(other_worker.id)]["state"] == "waiting"
        assert rows[str(other_worker.id)]["clock"]["state"] == "not_clocked_in"

    def test_approvals_payload_carries_no_money(
        self, office_staff: Staff, job: Job, worker: Staff
    ) -> None:
        """Approve time is for office staff who are not shown pay."""
        make_time_line(job, worker, accounting_date=DAY, approved=False)
        client = authenticated_client(office_staff)

        approvals = client.get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()
        day = client.get(f"{WORKSHOP_DAY_URL}?date={DAY.isoformat()}&staff_id={worker.id}").json()

        assert approvals["staff"][0]["entries"], "the check needs an entry to look inside"
        assert _money_keys(approvals) == set()
        assert _money_keys(day) == set()

    def test_workshop_staff_cannot_read_approvals(self, worker_client: Client) -> None:
        assert worker_client.get(APPROVALS_URL).status_code == 403
