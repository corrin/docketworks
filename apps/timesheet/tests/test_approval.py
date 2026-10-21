"""Office approval of worked time: a person's day at once, and what the screen is told."""

from collections.abc import Iterator
from datetime import date, time, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.errors import InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.models import AttendanceDay, TimesheetEvent
from apps.timesheet.services import approval, attendance
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
    make_break_line,
    make_leave_job,
    make_staff,
    make_time_line,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

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
    def test_a_waiting_lunch_alone_neither_holds_a_row_nor_hides_one(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff, break_job: Job
    ) -> None:
        """Lunch is logged, not hours: state and figures agree that it is neither."""
        make_time_line(job, worker, accounting_date=DAY, hours="7.500", approved=True)
        make_break_line(break_job, worker, DAY, hours="0.500", unpaid=True)
        make_break_line(break_job, other_worker, DAY, hours="0.500", unpaid=True)

        body = (
            authenticated_client(office_staff).get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()
        )

        rows = {row["staff_id"]: (row["state"], row["waiting_hours"]) for row in body["staff"]}
        # His job time is approved and only lunch waits: nothing is left for the office.
        assert rows[str(worker.id)] == ("nothing_waiting", 0.0)
        # Only a lunch on the day: expected and no job in, the person the office phones.
        assert rows[str(other_worker.id)] == ("nothing_entered", 0.0)

    def test_the_office_adds_after_the_persons_own_time(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """Each row opens the drawer where that person's day is up to, not on top of it."""
        attendance.set_clock_times(worker, DAY, time(7, 0), None, worker)
        make_time_line(
            job,
            worker,
            accounting_date=DAY,
            approved=False,
            start_time="07:00:00",
            end_time="12:00:00",
        )
        attendance.set_clock_times(other_worker, DAY, time(6, 30), None, other_worker)

        body = (
            authenticated_client(office_staff).get(f"{APPROVALS_URL}?date={DAY.isoformat()}").json()
        )

        rows = {row["staff_id"]: row["default_entry_start"] for row in body["staff"]}
        assert rows[str(worker.id)] == "12:00:00"
        # Nothing entered yet: from when that person clocked in.
        assert rows[str(other_worker.id)] == "06:30:00"
        assert "default_entry_start" not in body

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

    def test_day_summary_counts_people_by_state(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """Only people expected count, so a day can read complete without everyone on it."""
        saturday = DAY + timedelta(days=5)
        client = authenticated_client(office_staff)

        def read(day: date) -> dict[str, object]:
            body: dict[str, object] = client.get(f"{APPROVALS_URL}?date={day.isoformat()}").json()
            return body

        # A weekday: both are rostered. One done, one with nothing in.
        make_time_line(job, worker, accounting_date=DAY)
        assert read(DAY)["summary"] == {"expected": 2, "approved": 1, "standing": "in_progress"}
        # The other puts time in, the office approves it: the day is complete.
        make_time_line(job, other_worker, accounting_date=DAY, approved=False)
        assert read(DAY)["summary"] == {"expected": 2, "approved": 1, "standing": "in_progress"}
        approval.approve_day(other_worker, DAY, office_staff)
        assert read(DAY)["summary"] == {"expected": 2, "approved": 2, "standing": "complete"}

        # A Saturday: nobody is rostered, so nobody is expected and nothing is owed.
        weekend = read(saturday)
        assert weekend["summary"] == {"expected": 0, "approved": 0, "standing": "nobody_rostered"}
        assert {row["state"] for row in approval.day_approvals(saturday)["staff"]} == {
            "not_rostered"
        }
        # Someone who worked it is expected; the others still are not.
        make_time_line(job, worker, accounting_date=saturday, approved=False)
        assert read(saturday)["summary"] == {
            "expected": 1,
            "approved": 0,
            "standing": "in_progress",
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
            "cautions": ["Did not clock in", "Did not clock out"],
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


SWEEP_URL = f"{APPROVALS_URL}sweep/"


@pytest.fixture
def general_work(superuser: Staff) -> Job:
    """The internal job clocked time on no job is swept to, as ``create_shop_jobs`` leaves it."""
    defaults = CompanyDefaults.get_solo()
    job = make_job(defaults.shop_company, superuser, name="General work", status="special")
    defaults.general_work_job = job
    defaults.save(update_fields=["general_work_job"])
    return job


def _general_work_hours(general_work: Job, worker: Staff) -> list[str]:
    return [
        str(line.quantity)
        for line in CostLine.objects.filter(cost_set__job=general_work, staff=worker)
    ]


def _general_work_entries(general_work: Job, worker: Staff) -> list[tuple[str, str, str]]:
    """Each swept entry as (start, end, hours), in the order of the day."""
    return sorted(
        (line.meta["start_time"], line.meta["end_time"], str(line.quantity))
        for line in CostLine.objects.filter(cost_set__job=general_work, staff=worker)
    )


@pytest.mark.usefixtures("general_work")
class TestSweep:
    def test_each_stretch_between_breaks_and_jobs_is_its_own_entry(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Guards attendance.unallocated_windows: entries end where a break or a job starts."""
        # 07:00 to 12:00 puts the 08:30 paid break and the 11:30 lunch on the day.
        attendance.set_clock_times(worker, DAY, time(7, 0), time(12, 0), worker)
        make_time_line(
            job,
            worker,
            accounting_date=DAY,
            hours="1.000",
            approved=False,
            start_time="09:00:00",
            end_time="10:00:00",
        )

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _general_work_entries(general_work, worker) == [
            ("07:00:00", "08:30:00", "1.500"),
            ("08:45:00", "09:00:00", "0.250"),
            ("10:00:00", "11:30:00", "1.500"),
        ]
        assert result["swept_hours"] == 3.25

    def test_entries_without_times_are_laid_out_first(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Guards attendance.unallocated_windows: an untimed entry takes the day from clock-in."""
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 30), worker)
        make_time_line(job, worker, accounting_date=DAY, hours="1.000", approved=False)

        approval.sweep_person(worker, [DAY], office_staff)

        assert _general_work_entries(general_work, worker) == [("07:00:00", "08:30:00", "1.500")]

    def test_a_swept_entry_starts_and_stops_on_quarter_hours(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """Guards attendance.to_quarter: the clock keeps 06:52 and 08:08; the entry rounds."""
        attendance.set_clock_times(worker, DAY, time(6, 52), time(8, 8), worker)

        approval.sweep_person(worker, [DAY], office_staff)

        assert _general_work_entries(general_work, worker) == [("06:45:00", "08:15:00", "1.500")]
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert (row.clock_in, row.clock_out) == (time(6, 52), time(8, 8))

    def test_rounding_never_reaches_into_an_entry_beside_the_stretch(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Guards attendance.unallocated_windows: 07:23 rounds to 07:30 but his job starts 07:23."""
        attendance.set_clock_times(worker, DAY, time(6, 52), time(8, 8), worker)
        make_time_line(
            job,
            worker,
            accounting_date=DAY,
            hours="0.200",
            approved=False,
            start_time="07:23:00",
            end_time="07:35:00",
        )

        approval.sweep_person(worker, [DAY], office_staff)

        assert _general_work_entries(general_work, worker) == [
            ("06:45:00", "07:23:00", "0.630"),
            ("07:35:00", "08:15:00", "0.670"),
        ]

    def test_clocked_time_on_no_job_goes_to_general_work_and_the_day_is_approved(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Guards approval._sweep: the remainder is clocked time less what is on jobs."""
        # Clocked before the 08:30 break, so no break is put on the day.
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 30), worker)
        own = make_time_line(
            job,
            worker,
            accounting_date=DAY,
            hours="1.000",
            approved=False,
            start_time="06:00:00",
            end_time="07:00:00",
        )

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert result == {"swept_hours": 1.5, "approved_count": 1, "skipped": []}
        assert _general_work_hours(general_work, worker) == ["1.500"]
        swept = CostLine.objects.get(cost_set__job=general_work, staff=worker)
        assert swept.approved
        own.refresh_from_db()
        assert own.approved
        # The sweep reads the clock times; it never sets them.
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert (row.clock_in, row.clock_out) == (time(6, 0), time(8, 30))

    def test_a_day_still_clocked_in_is_skipped_and_left_alone(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Guards approval._sweep: no clock-out means no clocked time, so nothing moves."""
        attendance.set_clock_times(worker, DAY, time(7, 0), None, worker)
        own = make_time_line(job, worker, accounting_date=DAY, approved=False)

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert result["swept_hours"] == 0.0
        assert result["approved_count"] == 0
        assert [(skip["staff_id"], skip["reason"]) for skip in result["skipped"]] == [
            (str(worker.id), "still_clocked_in")
        ]
        assert _general_work_hours(general_work, worker) == []
        own.refresh_from_db()
        assert not own.approved
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert row.clock_out is None

    def test_a_day_over_its_clocked_time_moves_nothing_but_is_approved(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Guards approval._move_to_general_work: a negative remainder is no entry."""
        attendance.set_clock_times(worker, DAY, time(7, 0), time(8, 0), worker)
        own = make_time_line(job, worker, accounting_date=DAY, hours="3.000", approved=False)

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert result == {"swept_hours": 0.0, "approved_count": 1, "skipped": []}
        assert _general_work_hours(general_work, worker) == []
        own.refresh_from_db()
        assert own.approved

    def test_everyone_is_the_people_who_clocked_have_time_or_were_rostered(
        self,
        office_staff: Staff,
        job: Job,
        general_work: Job,
        worker: Staff,
        other_worker: Staff,
    ) -> None:
        """Guards approval._people_on: someone rostered who did nothing worked the standard day."""
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 0), worker)
        make_time_line(job, other_worker, accounting_date=DAY, approved=False)
        nobody = make_staff("not.here@example.com")

        result = approval.sweep_everyone([DAY], office_staff)

        assert result["skipped"] == []
        assert _general_work_hours(general_work, worker) == ["2.000"]
        assert _general_work_hours(general_work, nobody) != []
        assert AttendanceDay.objects.filter(staff=nobody, date=DAY).exists()

    def test_only_office_staff_sweep(self, worker: Staff) -> None:
        response = authenticated_client(worker).post(
            SWEEP_URL,
            {"start_date": DAY.isoformat(), "end_date": DAY.isoformat()},
            content_type="application/json",
        )

        assert response.status_code == 403, response.content

    def test_the_endpoint_sweeps_a_person_or_everyone_over_a_range(
        self, office_staff: Staff, worker: Staff, other_worker: Staff
    ) -> None:
        attendance.set_clock_times(worker, DAY, time(7, 0), time(8, 0), worker)
        tomorrow = DAY + timedelta(days=1)
        attendance.set_clock_times(worker, tomorrow, time(6, 0), time(8, 0), worker)
        attendance.set_clock_times(other_worker, DAY, time(6, 0), time(8, 30), other_worker)
        client = authenticated_client(office_staff)

        one = client.post(
            SWEEP_URL,
            {
                "start_date": DAY.isoformat(),
                "end_date": tomorrow.isoformat(),
                "staff_id": str(worker.id),
            },
            content_type="application/json",
        )
        everyone = client.post(
            SWEEP_URL,
            {"start_date": DAY.isoformat(), "end_date": DAY.isoformat()},
            content_type="application/json",
        )

        assert one.status_code == 200, one.content
        assert one.json() == {"swept_hours": 3.0, "approved_count": 0, "skipped": []}
        assert everyone.status_code == 200, everyone.content
        # The worker's day was swept already: only the other worker's 2.5 hours move.
        assert everyone.json()["swept_hours"] == 2.5

    @pytest.mark.usefixtures("general_work")
    def test_an_unclocked_rostered_day_is_the_standard_day(
        self, office_staff: Staff, worker: Staff
    ) -> None:
        """Guards approval._sweep and unallocated_windows: not clocking is the standard day."""
        standard = attendance.standard_day(DAY)
        assert standard is not None
        [shown] = [
            row for row in approval.day_approvals(DAY)["staff"] if row["staff_id"] == str(worker.id)
        ]

        result = approval.sweep_person(worker, [DAY], office_staff)

        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert (row.clock_in, row.clock_out) == (standard.start, standard.end)
        assert attendance.day_state(row) == "sent"
        assert result["skipped"] == []
        assert result["swept_hours"] == shown["unallocated_hours"]
        assert result["swept_hours"] > 0

    def test_an_unclocked_day_of_leave_sweeps_nothing(
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """Guards attendance.unallocated_windows: unclocked, his leave is his standard day."""
        leave_job = make_leave_job(company, superuser, "Annual Leave")
        leave = make_time_line(leave_job, worker, accounting_date=DAY, hours="8.000")
        CostLine.objects.filter(pk=leave.pk).update(managed_by="leave")

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _general_work_entries(general_work, worker) == []
        assert result["swept_hours"] == 0.0

    @pytest.mark.usefixtures("general_work")
    def test_an_unclocked_day_nobody_was_rostered_for_is_skipped(
        self, office_staff: Staff, worker: Staff
    ) -> None:
        """Guards approval._sweep: a weekend nobody clocked is no day worked."""
        saturday = DAY + timedelta(days=5)

        result = approval.sweep_person(worker, [saturday], office_staff)

        assert [skip["reason"] for skip in result["skipped"]] == ["no_clock_times"]
        assert not AttendanceDay.objects.filter(staff=worker, date=saturday).exists()

    def test_leave_on_the_day_takes_none_of_the_clocked_time(
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """Guards attendance.unallocated_windows: leave on the day leaves clocked hours free."""
        leave_job = make_leave_job(company, superuser, "Annual Leave")
        leave = make_time_line(leave_job, worker, accounting_date=DAY, hours="4.000")
        CostLine.objects.filter(pk=leave.pk).update(managed_by="leave")
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 0), worker)

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _general_work_entries(general_work, worker) == [("06:00:00", "08:00:00", "2.000")]
        assert result["swept_hours"] == 2.0

    def test_a_clock_change_takes_off_swept_time_it_no_longer_covers(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """Guards attendance.drop_sweep_outside_clock: an earlier finish is not paid after it."""
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 0), worker)
        approval.sweep_person(worker, [DAY], office_staff)

        attendance.set_clock_times(worker, DAY, time(6, 0), time(7, 0), office_staff)

        assert _general_work_entries(general_work, worker) == []
        approval.sweep_person(worker, [DAY], office_staff)
        assert _general_work_entries(general_work, worker) == [("06:00:00", "07:00:00", "1.000")]

    def test_a_clock_change_keeps_swept_time_it_still_covers(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """Guards attendance.drop_sweep_outside_clock: bounds are the sweep's quarter hours."""
        attendance.set_clock_times(worker, DAY, time(6, 52), time(8, 8), worker)
        approval.sweep_person(worker, [DAY], office_staff)

        attendance.set_clock_times(worker, DAY, time(6, 50), time(8, 10), office_staff)

        assert _general_work_entries(general_work, worker) == [("06:45:00", "08:15:00", "1.500")]

    def test_general_work_set_to_break_or_leave_is_refused(
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        break_job: Job,
        worker: Staff,
    ) -> None:
        """Guards approval._general_work_job_id: neither breaks nor leave are worked time."""
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 0), worker)
        defaults = CompanyDefaults.get_solo()
        for wrong in (break_job, make_leave_job(company, superuser, "Annual Leave")):
            defaults.general_work_job = wrong
            defaults.save(update_fields=["general_work_job"])

            with pytest.raises(approval.GeneralWorkNotSetUpError, match=wrong.name):
                approval.sweep_person(worker, [DAY], office_staff)

    @pytest.mark.usefixtures("general_work")
    def test_a_swept_day_is_sent(self, office_staff: Staff, worker: Staff) -> None:
        """Guards approval._send_for_him: sweeping submits, so his app stops asking for the day."""
        attendance.set_clock_times(worker, DAY, time(6, 0), time(8, 0), worker)

        approval.sweep_person(worker, [DAY], office_staff)

        assert attendance.pending_day(worker, DAY + timedelta(days=1)) is None
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert attendance.day_state(row) == "sent"


class TestSweepDays:
    """Guards approval.sweep_days: the range a sweep may take."""

    def test_today_and_the_six_days_before_are_a_sweep(self) -> None:
        today = timezone.localdate()

        days = approval.sweep_days(today - timedelta(days=6), today)

        assert days[0] == today - timedelta(days=6)
        assert days[-1] == today
        assert len(days) == approval.SWEEP_MOST_DAYS

    def test_a_day_after_today_is_refused(self) -> None:
        today = timezone.localdate()

        with pytest.raises(InvalidInputError, match="after today"):
            approval.sweep_days(today, today + timedelta(days=1))

    def test_more_than_a_week_is_refused(self) -> None:
        today = timezone.localdate()

        with pytest.raises(InvalidInputError, match="one week"):
            approval.sweep_days(today - timedelta(days=7), today)

    def test_an_end_before_the_start_is_refused(self) -> None:
        with pytest.raises(InvalidInputError, match="before the start"):
            approval.sweep_days(DAY, DAY - timedelta(days=1))
