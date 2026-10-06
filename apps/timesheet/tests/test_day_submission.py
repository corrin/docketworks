"""Filling and sending a day: the arithmetic, breaks, placement, and all-or-nothing sending."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.errors import ConflictError, InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import is_unpaid_time
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import (
    approval,
    attendance,
    day_submission,
    timesheet_entry_options,
    weekly_timesheet_service,
    workshop_timesheet_service,
)
from apps.timesheet.services.attendance import Window
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
    make_leave_job,
    make_time_line,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

DAY = WEEK_START
MORNING = Window(time(8, 30), time(8, 45))
LUNCH = Window(time(11, 30), time(12, 0))
AFTERNOON = Window(time(13, 30), time(13, 45))
STANDARD_BREAKS = [MORNING, LUNCH, AFTERNOON]
SUBMIT_URL = "/api/timesheets/my-day/submit/"
BREAKS_URL = "/api/timesheets/my-day/breaks/"
DAY_URL = "/api/job/workshop/timesheets/"
PLACEMENT_URL = "/api/timesheets/my-day/placement/"
JOBS_URL = "/api/timesheets/jobs/"


def _row(job: Job, hours: str, *, time_and_a_half: bool = False) -> day_submission.FillRow:
    return {
        "job_id": job.id,
        "hours": Decimal(hours),
        "description": None,
        "time_and_a_half": time_and_a_half,
    }


def _spans(lines: list[day_submission.LaidLine]) -> list[tuple[str, str, Decimal]]:
    return [(f"{line['start']:%H:%M}", f"{line['end']:%H:%M}", line["hours"]) for line in lines]


def _clocked(worker: Staff, start: time = time(6, 30), finish: time = time(15, 0)) -> None:
    attendance.set_clock_times(worker, DAY, start, finish, worker)


def _day(worker: Staff) -> workshop_timesheet_service.WorkshopDayData:
    return workshop_timesheet_service.list_entries(worker, DAY)


def _breaks(worker: Staff) -> list[tuple[str, str, bool]]:
    return [
        (f"{each['start']:%H:%M}", f"{each['end']:%H:%M}", each["paid"])
        for each in _day(worker)["breaks"]
    ]


class TestPlacement:
    """An entry's hours are the truth; its times are the picture, stepping over breaks."""

    def test_a_six_hour_job_from_seven_ends_at_two(self) -> None:
        """The owner's example: 7 + 6 + 0:15 + 0:30 + 0:15."""
        assert attendance.finish_for(time(7, 0), Decimal("6"), STANDARD_BREAKS) == time(14, 0)

    def test_work_that_ends_as_a_break_starts_does_not_step_over_it(self) -> None:
        assert attendance.finish_for(time(7, 0), Decimal("1.5"), STANDARD_BREAKS) == time(8, 30)

    def test_work_begun_inside_a_break_begins_when_the_break_ends(self) -> None:
        assert attendance.finish_for(time(11, 45), Decimal("1"), STANDARD_BREAKS) == time(13, 0)

    def test_hours_are_the_span_less_the_breaks_inside_it(self) -> None:
        assert attendance.hours_for(time(7, 0), time(14, 0), STANDARD_BREAKS) == Decimal("6.00")
        assert attendance.hours_for(time(9, 0), time(10, 0), STANDARD_BREAKS) == Decimal("1.00")

    def test_hours_past_midnight_are_refused(self) -> None:
        with pytest.raises(InvalidInputError, match="past midnight"):
            attendance.finish_for(time(20, 0), Decimal("5"), [])

    def test_the_drawer_is_answered_by_the_same_rule(
        self, worker_client: Client, worker: Staff
    ) -> None:
        """Hours give the finish, a finish gives the hours, and nothing is written."""
        _clocked(worker, time(7, 0), time(15, 0))
        query = f"{PLACEMENT_URL}?date={DAY.isoformat()}&start=07:00"

        forward = worker_client.get(f"{query}&hours=6").json()
        back = worker_client.get(f"{query}&finish=14:00").json()
        neither = worker_client.get(query)

        assert forward == {"start": "07:00:00", "finish": "14:00:00", "hours": 6.0}
        assert back == {"start": "07:00:00", "finish": "14:00:00", "hours": 6.0}
        assert neither.status_code == 400
        for refused in ("0", "-1", "100000"):
            assert worker_client.get(f"{query}&hours={refused}").status_code == 422
        assert not CostLine.objects.filter(staff=worker, cost_set__job__status="draft").exists()


class TestHoursToFill:
    def test_span_deducts_unpaid_breaks(self) -> None:
        assert attendance.paid_span_hours(time(6, 30), time(15, 0), []) == Decimal("8.5")
        assert attendance.paid_span_hours(time(6, 30), time(15, 0), [LUNCH]) == Decimal("8")

    def test_overlapping_unpaid_breaks_come_off_once(self) -> None:
        """He moved lunch over an unpaid break he had added: half an hour away, not 45 minutes."""
        overlapping = [LUNCH, Window(time(11, 45), time(12, 0))]

        assert attendance.paid_span_hours(time(6, 30), time(15, 0), overlapping) == Decimal("8")

    def test_span_rounds_to_the_quarter_hour(self) -> None:
        """A real clock gives 06:28 to 15:04; the worker is never shown 8.1."""
        assert attendance.paid_span_hours(time(6, 28), time(15, 4), [LUNCH]) == Decimal("8")
        assert attendance.paid_span_hours(time(6, 30), time(15, 8), [LUNCH]) == Decimal("8.25")

    def test_the_standard_day_is_seven_and_a_half_hours_of_jobs_and_eight_paid(
        self, worker: Staff, job: Job
    ) -> None:
        """Eight hours to fill; his two paid breaks are entered; 7.5 is left for jobs."""
        _clocked(worker)

        assert _day(worker)["fill"] == {
            "to_fill_hours": 8.0,
            "break_hours": 0.5,
            "entered_hours": 0.0,
            "to_go_hours": 7.5,
        }
        day_submission.submit_day(worker, DAY, [_row(job, "7.5")], None, timezone.now())
        day = _day(worker)
        assert day["fill"] is not None and day["fill"]["to_go_hours"] == 0.0
        # Paid for eight: seven and a half on the job, half an hour of paid breaks.
        assert day["summary"]["total_hours"] == 8.0

    def test_to_go_goes_negative_when_he_is_over(self, worker: Staff, job: Job) -> None:
        _clocked(worker)
        make_time_line(job, worker, accounting_date=DAY, hours="8.000", approved=False)

        fill = _day(worker)["fill"]

        assert fill is not None and fill["to_go_hours"] == -0.5

    def test_there_is_nothing_to_fill_until_both_clock_times_are_known(self, worker: Staff) -> None:
        assert attendance.fill_figures(None, Decimal("3"), []) is None
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)
        open_row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert attendance.fill_figures(open_row, Decimal("3"), []) is None


def _lunch(worker: Staff, break_job: Job) -> CostLine:
    [lunch] = [
        line
        for line in CostLine.objects.filter(staff=worker, cost_set__job=break_job).select_related(
            "xero_pay_item"
        )
        if is_unpaid_time(line)
    ]
    return lunch


def _week_row(worker: Staff) -> weekly_timesheet_service.WeeklyStaffData:
    [week_row] = [
        row
        for row in weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]
        if row["staff_id"] == str(worker.id)
    ]
    return week_row


class TestBreaks:
    """Every break is a line on the Break job: a paid break is paid time, lunch is logged unpaid."""

    def test_defaults_are_generated_once_when_the_span_covers_them(
        self, worker: Staff, break_job: Job
    ) -> None:
        _clocked(worker)

        assert _breaks(worker) == [
            ("08:30", "08:45", True),
            ("11:30", "12:00", False),
            ("13:30", "13:45", True),
        ]
        assert CostLine.objects.filter(staff=worker, cost_set__job=break_job).count() == 3

    def test_paid_breaks_are_ordinary_entries_and_are_posted_and_totalled_as_time(
        self, worker: Staff, break_job: Job
    ) -> None:
        """Nothing about a paid break is special: a quarter hour at his wage, billed to nobody."""
        _clocked(worker)

        lines = [
            line
            for line in CostLine.objects.filter(
                staff=worker, cost_set__job=break_job
            ).select_related("xero_pay_item")
            if not is_unpaid_time(line)
        ]

        assert [line.quantity for line in lines] == [Decimal("0.25"), Decimal("0.25")]
        assert all(line.unit_cost == Decimal("48.00") for line in lines)
        assert all(line.unit_rev == Decimal("0.00") for line in lines)
        assert all(line.meta["is_billable"] is False for line in lines)
        # His own, so waiting for the office like the rest of his time.
        assert all(line.approved is False for line in lines)
        week_row = _week_row(worker)
        assert week_row["total_hours"] == Decimal("0.50")
        assert week_row["total_unapproved_hours"] == Decimal("0.50")

    def test_lunch_is_logged_at_the_unpaid_rate_and_is_in_no_hours_figure(
        self, worker_client: Client, worker: Staff, job: Job, break_job: Job
    ) -> None:
        """Owner, 2026-10-06: "Logged, but not hours and not sent to Xero".

        The week's posted lines are held to the same in apps/xero/tests/test_payroll_push.py,
        since this app may not import the payroll push.
        """
        make_time_line(job, worker, accounting_date=DAY, hours="5.000")
        attendance.set_clock_times(worker, DAY, time(10, 0), time(13, 0), worker)
        lunch = _lunch(worker, break_job)

        def figures() -> tuple[object, object, object]:
            day = worker_client.get(f"{DAY_URL}?date={DAY.isoformat()}").json()
            return day["summary"], day["week"], _week_row(worker)

        assert (lunch.quantity, lunch.desc, lunch.unit_cost) == (
            Decimal("0.50"),
            "Lunch",
            Decimal("0.00"),
        )
        assert lunch.xero_pay_item is not None and lunch.xero_pay_item.name == "Unpaid"
        assert _breaks(worker) == [("11:30", "12:00", False)]
        with_lunch = figures()
        attendance.remove_break(lunch.id, worker)

        assert figures() == with_lunch

    def test_an_extra_long_lunch_is_unpaid_and_a_long_paid_break_is_paid(
        self, worker: Staff, break_job: Job
    ) -> None:
        """Log what happened: lengthening a break keeps its kind."""
        _clocked(worker)
        lunch = _lunch(worker, break_job)
        morning = next(each for each in _day(worker)["breaks"] if each["paid"])
        assert morning["id"] is not None

        attendance.change_break(lunch.id, time(11, 30), time(12, 30), worker)
        attendance.change_break(UUID(morning["id"]), time(8, 30), time(9, 0), worker)

        fill = _day(worker)["fill"]
        # Eight and a half here less an hour's lunch; the paid breaks are now 45m.
        assert fill is not None
        assert (fill["to_fill_hours"], fill["break_hours"]) == (7.5, 0.75)
        assert _week_row(worker)["total_hours"] == Decimal("0.75")

    def test_generated_breaks_are_never_late_or_remote(self, worker: Staff, break_job: Job) -> None:
        """Nobody typed them: standard hours used a week later still put them on unmarked."""
        company = CompanyDefaults.get_solo()
        company.latitude = Decimal("-36.850000")
        company.longitude = Decimal("174.760000")
        company.save(update_fields=["latitude", "longitude"])

        attendance.use_standard_hours(worker, DAY, worker)

        lines = list(CostLine.objects.filter(staff=worker, cost_set__job=break_job))
        assert len(lines) == 3
        assert not any(line.remote_entry for line in lines)
        assert not any(workshop_timesheet_service.entered_late(line) for line in lines)

    def test_a_fifteen_minute_job_is_not_billed_for_the_break_beside_it(
        self, worker: Staff, job: Job, break_job: Job
    ) -> None:
        """The owner's reason: a break put inside a 15 minute job would double its bill."""
        _clocked(worker)

        day_submission.submit_day(worker, DAY, [_row(job, "0.25")], None, timezone.now())

        [on_the_job] = CostLine.objects.filter(staff=worker, cost_set__job=job)
        assert on_the_job.quantity == Decimal("0.25")
        assert on_the_job.meta["is_billable"] is True
        assert on_the_job.unit_rev > 0
        on_breaks = CostLine.objects.filter(staff=worker, cost_set__job=break_job)
        assert {line.unit_rev for line in on_breaks} == {Decimal("0.00")}

    def test_planned_breaks_show_before_clock_out_and_write_nothing(self, worker: Staff) -> None:
        """The day has its shape from the moment he opens it."""
        unclocked = _breaks(worker)
        attendance.set_clock_times(worker, DAY, time(9, 0), None, worker)
        at_work = _day(worker)["breaks"]

        # Nobody has clocked: the standard day's three.
        assert unclocked == [
            ("08:30", "08:45", True),
            ("11:30", "12:00", False),
            ("13:30", "13:45", True),
        ]
        # In at nine: the morning break has gone by.
        assert [(each["start"], each["planned"], each["id"]) for each in at_work] == [
            (time(11, 30), True, None),
            (time(13, 30), True, None),
        ]
        assert not CostLine.objects.filter(staff=worker).exists()

    def test_a_break_added_while_at_work_shows_and_is_not_put_on_twice(
        self, worker: Staff, break_job: Job
    ) -> None:
        """He took lunch late and said so before clocking out: one lunch, his."""
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)
        attendance.add_break(worker, DAY, time(12, 15), time(12, 45), paid=False, actor=worker)

        at_work = _breaks(worker)
        on_the_office_row = [
            (f"{each['start']:%H:%M}", each["planned"])
            for row in approval.day_approvals(DAY)["staff"]
            if row["staff_id"] == str(worker.id)
            for each in row["breaks"]
        ]
        _clocked(worker)

        # Shown at once, beside the paid breaks still to come; no planned lunch.
        assert at_work == [
            ("08:30", "08:45", True),
            ("12:15", "12:45", False),
            ("13:30", "13:45", True),
        ]
        assert on_the_office_row == [("08:30", True), ("12:15", False), ("13:30", True)]
        # Clocking out puts on the two paid breaks and no second lunch.
        assert _breaks(worker) == at_work
        assert CostLine.objects.filter(staff=worker, cost_set__job=break_job).count() == 3

    def test_a_late_morning_break_stands_in_for_the_morning_one(self, worker: Staff) -> None:
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)
        attendance.add_break(worker, DAY, time(10, 0), time(10, 15), paid=True, actor=worker)

        _clocked(worker)

        assert _breaks(worker) == [
            ("10:00", "10:15", True),
            ("11:30", "12:00", False),
            ("13:30", "13:45", True),
        ]

    def test_a_break_he_did_not_have_is_never_entered(self, worker: Staff, break_job: Job) -> None:
        """He left at noon: the afternoon break was planned, and is not paid."""
        _clocked(worker, time(6, 30), time(12, 0))

        assert _breaks(worker) == [("08:30", "08:45", True), ("11:30", "12:00", False)]
        assert CostLine.objects.filter(staff=worker, cost_set__job=break_job).count() == 2

    def test_working_through_lunch_is_deleting_it(self, worker: Staff, break_job: Job) -> None:
        """He worked through and deleted it; the office fixing his finish does not put it back."""
        _clocked(worker)
        attendance.remove_break(_lunch(worker, break_job).id, worker)

        fill = _day(worker)["fill"]
        _clocked(worker, time(6, 30), time(15, 30))

        assert fill is not None and fill["to_fill_hours"] == 8.5
        assert _breaks(worker) == [("08:30", "08:45", True), ("13:30", "13:45", True)]

    def test_removing_a_paid_break_leaves_that_time_to_fill(self, worker: Staff) -> None:
        """He is paid for it only if he books it to a job, which is right."""
        _clocked(worker)
        morning = next(each for each in _day(worker)["breaks"] if each["paid"])
        assert morning["id"] is not None

        attendance.remove_break(UUID(morning["id"]), worker)

        fill = _day(worker)["fill"]
        assert fill is not None
        assert (fill["break_hours"], fill["to_go_hours"]) == (0.25, 7.75)

    def test_a_break_outside_the_clocked_span_does_not_shrink_the_day(
        self, worker: Staff, break_job: Job
    ) -> None:
        """Lunch moved to after he had gone: only the part inside his hours comes off."""
        _clocked(worker)
        lunch = _lunch(worker, break_job)

        attendance.change_break(lunch.id, time(14, 45), time(15, 15), worker)
        straddling = _day(worker)["fill"]
        attendance.change_break(lunch.id, time(16, 0), time(16, 30), worker)
        outside = _day(worker)["fill"]

        assert straddling is not None and straddling["to_fill_hours"] == 8.25
        assert outside is not None and outside["to_fill_hours"] == 8.5

    def test_a_break_is_moved_as_the_entry_it_is(
        self, worker: Staff, office_staff: Staff, break_job: Job
    ) -> None:
        _clocked(worker)
        morning = CostLine.objects.filter(staff=worker, cost_set__job=break_job).first()
        assert morning is not None

        attendance.change_break(morning.id, time(9, 0), time(9, 15), worker)
        morning.refresh_from_db()
        assert (morning.meta["start_time"], morning.meta["end_time"]) == ("09:00:00", "09:15:00")
        # Once the office approves it, it is locked for him like any approved time.
        CostLine.objects.filter(pk=morning.pk).update(approved=True)
        with pytest.raises(ConflictError, match="approved"):
            attendance.remove_break(morning.id, worker)
        attendance.remove_break(morning.id, office_staff)
        assert not CostLine.objects.filter(pk=morning.pk).exists()

    def test_a_job_entry_is_not_a_break(self, worker: Staff, job: Job) -> None:
        """The break endpoints move breaks only: an entry's id there is not found."""
        line = make_time_line(job, worker, accounting_date=DAY, approved=False)

        with pytest.raises(attendance.BreakNotFoundError):
            attendance.remove_break(line.id, worker)

    def test_a_worker_cannot_change_another_persons_break(
        self, worker_client: Client, other_worker: Staff, office_staff: Staff, break_job: Job
    ) -> None:
        attendance.set_clock_times(other_worker, DAY, time(6, 30), time(15, 0), other_worker)
        theirs = _lunch(other_worker, break_job)
        url = f"{BREAKS_URL}{theirs.id}/"
        body = {"start": "12:00", "end": "12:30"}

        moved = worker_client.put(url, data=body, content_type="application/json")
        removed = worker_client.delete(url)
        added = worker_client.post(
            BREAKS_URL,
            data={
                "date": DAY.isoformat(),
                "start": "13:00",
                "end": "13:15",
                "paid": False,
                "staff_id": str(other_worker.id),
            },
            content_type="application/json",
        )
        by_the_office = authenticated_client(office_staff).put(
            url, data=body, content_type="application/json"
        )

        assert (moved.status_code, removed.status_code, added.status_code) == (403, 403, 403)
        assert by_the_office.status_code == 204
        theirs.refresh_from_db()
        assert theirs.meta["start_time"] == "12:00:00"

    def test_zero_minutes_switches_a_default_off(self, worker: Staff) -> None:
        company = CompanyDefaults.get_solo()
        company.morning_break_minutes = 0
        company.full_clean()
        company.save(update_fields=["morning_break_minutes"])

        _clocked(worker)

        assert _breaks(worker) == [("11:30", "12:00", False), ("13:30", "13:45", True)]

    def test_a_break_length_is_nothing_or_five_minutes_to_two_hours(self) -> None:
        company = CompanyDefaults.get_solo()
        company.lunch_minutes = 3
        with pytest.raises(ValidationError, match="5 to 120 minutes"):
            company.full_clean()

    def test_a_day_is_refused_until_breaks_are_set_up(self, worker: Staff) -> None:
        """A day made without its paid breaks would pay half an hour short, silently."""
        CompanyDefaults.objects.update(break_job=None)

        with pytest.raises(attendance.BreaksNotSetUpError, match="Tell the office"):
            _clocked(worker)

        assert not AttendanceDay.objects.filter(staff=worker).exists()


class TestLayout:
    def test_rows_are_placed_one_after_another_each_stepping_over_breaks(self, job: Job) -> None:
        lines = day_submission.lay_out_rows(
            time(6, 30), [_row(job, "3"), _row(job, "2"), _row(job, "2.5")], STANDARD_BREAKS
        )

        # One entry per row, never split: 3h spans the morning break, 2.5h spans two.
        assert _spans(lines) == [
            ("06:30", "09:45", Decimal("3")),
            ("09:45", "12:15", Decimal("2")),
            ("12:15", "15:00", Decimal("2.5")),
        ]

    def test_hours_are_quarter_hours(self, job: Job) -> None:
        with pytest.raises(InvalidInputError, match="quarter hours"):
            day_submission.lay_out_rows(time(6, 30), [_row(job, "1.1")], [])


class TestEntryTimes:
    def test_hours_may_be_less_than_the_span_but_not_more(
        self, worker_client: Client, job: Job
    ) -> None:
        body = {"job_id": str(job.id), "accounting_date": DAY.isoformat()}

        spanning = worker_client.post(
            DAY_URL,
            data={**body, "hours": "6", "start_time": "07:00", "end_time": "14:00"},
            content_type="application/json",
        )
        too_many = worker_client.post(
            DAY_URL,
            data={**body, "hours": "8", "start_time": "07:00", "end_time": "14:00"},
            content_type="application/json",
        )

        assert spanning.status_code == 201, spanning.content
        assert too_many.status_code == 400
        assert "cannot be more than" in too_many.json()["detail"]

    def test_hours_that_would_run_past_midnight_are_saved_without_times(
        self, worker_client: Client, worker: Staff, job: Job
    ) -> None:
        """Hours are the truth: twelve hours from one o'clock still save, with no picture."""
        _clocked(worker, time(7, 0), time(15, 0))
        body = {"job_id": str(job.id), "accounting_date": DAY.isoformat()}
        worker_client.post(DAY_URL, data={**body, "hours": "5"}, content_type="application/json")

        late = worker_client.post(
            DAY_URL, data={**body, "hours": "12"}, content_type="application/json"
        )

        assert late.status_code == 201, late.content
        assert (late.json()["start_time"], late.json()["end_time"]) == (None, None)
        assert late.json()["hours"] == 12.0

    def test_an_entry_saved_without_times_is_placed_after_the_previous_one(
        self, worker_client: Client, worker: Staff, job: Job
    ) -> None:
        """Hours are all he has to say; the day still draws."""
        _clocked(worker, time(7, 0), time(15, 0))
        body = {"job_id": str(job.id), "accounting_date": DAY.isoformat()}

        first = worker_client.post(
            DAY_URL, data={**body, "hours": "6"}, content_type="application/json"
        ).json()
        second = worker_client.post(
            DAY_URL, data={**body, "hours": "0.5"}, content_type="application/json"
        ).json()

        assert (first["start_time"], first["end_time"]) == ("07:00:00", "14:00:00")
        assert (second["start_time"], second["end_time"]) == ("14:00:00", "14:30:00")


class TestSubmitDay:
    def test_rows_become_entries_and_the_day_is_sent(self, worker: Staff, job: Job) -> None:
        _clocked(worker)
        now = timezone.now()

        day = day_submission.submit_day(
            worker, DAY, [_row(job, "3"), _row(job, "2", time_and_a_half=True)], None, now
        )

        assert day["day"]["state"] == "sent"
        assert [(entry["start_time"], entry["end_time"]) for entry in day["entries"]] == [
            (time(6, 30), time(9, 45)),
            (time(9, 45), time(12, 15)),
        ]
        assert [entry["wage_rate_multiplier"] for entry in day["entries"]] == [1.0, 1.5]
        assert all(not entry["approved"] for entry in day["entries"])
        assert day["fill"] == {
            "to_fill_hours": 8.0,
            "break_hours": 0.5,
            "entered_hours": 5.0,
            "to_go_hours": 2.5,
        }

    def test_a_row_on_a_shop_job_is_saved_unbillable(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """The sheet has no billable tick: bench time must not be refused as billable."""
        bench = make_job(company, superuser, name="Bench", status="special")
        _clocked(worker)

        day = day_submission.submit_day(
            worker, DAY, [_row(bench, "3"), _row(job, "2")], None, timezone.now()
        )

        assert [entry["is_billable"] for entry in day["entries"]] == [False, True]

    def test_submit_requires_clock_out(self, worker: Staff, job: Job) -> None:
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)

        with pytest.raises(ConflictError, match="Clock out"):
            day_submission.submit_day(worker, DAY, [_row(job, "3")], None, timezone.now())

        assert not CostLine.objects.filter(staff=worker).exists()

    def test_submit_is_all_or_nothing(self, worker: Staff, job: Job) -> None:
        """A row that cannot be saved leaves the day as it was, and unsent."""
        _clocked(worker)
        unknown: day_submission.FillRow = {
            "job_id": uuid4(),
            "hours": Decimal("2"),
            "description": None,
            "time_and_a_half": False,
        }

        with pytest.raises(Job.DoesNotExist):
            day_submission.submit_day(worker, DAY, [_row(job, "3"), unknown], None, timezone.now())

        assert not CostLine.objects.filter(staff=worker, cost_set__job=job).exists()
        assert AttendanceDay.objects.get(staff=worker, date=DAY).submitted_at is None

    def test_every_filled_entry_is_judged_by_where_the_phone_is(
        self, worker_client: Client, worker: Staff, job: Job
    ) -> None:
        """Sent from the workshop, no entry is marked; the location reaches each one."""
        company = CompanyDefaults.get_solo()
        company.latitude = Decimal("-36.850000")
        company.longitude = Decimal("174.760000")
        company.save(update_fields=["latitude", "longitude"])
        _clocked(worker)
        body = {
            "date": DAY.isoformat(),
            "rows": [
                {"job_id": str(job.id), "hours": "3"},
                {"job_id": str(job.id), "hours": "2"},
            ],
        }

        at_work = worker_client.post(
            SUBMIT_URL,
            data={**body, "location": {"latitude": -36.85, "longitude": 174.76}},
            content_type="application/json",
        )

        assert at_work.status_code == 200, at_work.content
        assert [entry["remote_entry"] for entry in at_work.json()["entries"]] == [False, False]
        elsewhere = worker_client.post(SUBMIT_URL, data=body, content_type="application/json")
        assert [entry["remote_entry"] for entry in elsewhere.json()["entries"]][-2:] == [
            True,
            True,
        ]

    def test_sending_with_hours_still_to_go_is_allowed(self, worker: Staff) -> None:
        _clocked(worker)

        day = day_submission.submit_day(worker, DAY, [], None, timezone.now())

        assert day["day"]["state"] == "sent"
        assert day["fill"] is not None and day["fill"]["to_go_hours"] == 7.5


class TestPendingDay:
    def test_a_day_clocked_out_and_not_sent_is_pending(self, worker: Staff) -> None:
        _clocked(worker)

        assert attendance.pending_day(worker, DAY + timedelta(days=1)) == {
            "date": DAY,
            "state": "clocked_out",
        }

    def test_a_sent_day_is_not_pending(self, worker: Staff) -> None:
        _clocked(worker)
        day_submission.submit_day(worker, DAY, [], None, timezone.now())

        assert attendance.pending_day(worker, DAY + timedelta(days=1)) is None

    def test_a_day_he_never_clocked_is_never_the_pending_day(self, worker: Staff, job: Job) -> None:
        """Entries without a clock-in ask nothing of him; the office typed that card."""
        make_time_line(job, worker, accounting_date=DAY, approved=False)

        assert attendance.pending_day(worker, DAY + timedelta(days=1)) is None


class TestCalendarBounds:
    def test_the_calendar_opens_on_the_working_day_stretched_to_the_clocked_span(
        self, worker: Staff
    ) -> None:
        _clocked(worker, time(6, 30), time(17, 10))
        row = AttendanceDay.objects.get(staff=worker, date=DAY)

        bounds = attendance.calendar_bounds(row, Window(time(7, 0), time(15, 0)), [])

        assert bounds == {"start": time(5, 0), "end": time(18, 10)}

    def test_a_short_clocking_does_not_hide_the_working_day(self, worker: Staff) -> None:
        """Clocked 07:30 to 08:00 by mistake: the hours he would book are still there."""
        _clocked(worker, time(7, 30), time(8, 0))
        row = AttendanceDay.objects.get(staff=worker, date=DAY)

        bounds = attendance.calendar_bounds(row, Window(time(7, 0), time(15, 0)), [])

        assert bounds == {"start": time(6, 0), "end": time(16, 0)}

    def test_it_widens_for_an_entry_outside_the_day(self) -> None:
        bounds = attendance.calendar_bounds(
            None, Window(time(7, 0), time(15, 0)), [(time(17, 0), time(18, 30))]
        )

        assert bounds == {"start": time(6, 0), "end": time(19, 30)}


class TestSameMinuteTap:
    def test_a_tap_out_in_the_minute_of_the_tap_in_has_its_own_words(self, worker: Staff) -> None:
        """The midnight wording is only ever shown for the midnight case."""
        moment = datetime.combine(DAY, time(6, 30, 10), tzinfo=timezone.get_current_timezone())
        attendance.clock_in(worker, moment)

        with pytest.raises(attendance.ClockingRefusedError, match="a moment ago"):
            attendance.clock_out(worker, moment + timedelta(seconds=30))


class TestJobButtons:
    def test_pinned_jobs_exclude_leave_jobs(
        self, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        """Standing shop jobs with recent time, most hours first; never leave or a customer job."""
        today = timezone.localdate()
        bench = make_job(company, superuser, name="Bench", status="special")
        cleanup = make_job(company, superuser, name="Clean-up", status="special")
        stale = make_job(company, superuser, name="Old training", status="special")
        leave = make_leave_job(company, superuser, "Annual Leave")
        make_time_line(bench, worker, accounting_date=today, hours="2.000")
        make_time_line(cleanup, worker, accounting_date=today, hours="5.000")
        make_time_line(stale, worker, accounting_date=today - timedelta(days=45))
        make_time_line(leave, worker, accounting_date=today)
        make_time_line(job, worker, accounting_date=today)

        assert timesheet_entry_options.pinned_job_ids(today) == [cleanup.id, bench.id]

    def test_recent_jobs_ignore_future_dates(
        self, company: Company, superuser: Staff, worker: Staff, other_worker: Staff, job: Job
    ) -> None:
        """The last three days anyone worked on a customer job, the caller's own first."""
        today = timezone.localdate()
        theirs = make_job(company, superuser, name="Their job")
        older = make_job(company, superuser, name="Four working days ago")
        booked_ahead = make_job(company, superuser, name="Booked ahead")
        leave = make_leave_job(company, superuser, "Annual Leave")
        make_time_line(job, worker, accounting_date=today - timedelta(days=5), hours="1.000")
        make_time_line(
            theirs, other_worker, accounting_date=today - timedelta(days=6), hours="8.000"
        )
        make_time_line(
            theirs, other_worker, accounting_date=today - timedelta(days=7), hours="8.000"
        )
        make_time_line(older, worker, accounting_date=today - timedelta(days=8))
        make_time_line(booked_ahead, worker, accounting_date=today + timedelta(days=1))
        # A week of leave since then must not empty the list.
        make_time_line(leave, worker, accounting_date=today)

        assert timesheet_entry_options.recent_job_ids(worker, today) == [job.id, theirs.id]

    def test_the_break_job_is_not_offered_as_a_job_or_counted_as_one(
        self, worker_client: Client, worker: Staff, job: Job, break_job: Job
    ) -> None:
        """His breaks are his time, but Break is not a job he picks or worked on."""
        _clocked(worker)
        make_time_line(job, worker, accounting_date=DAY, approved=False)

        jobs = worker_client.get(JOBS_URL).json()
        searched = worker_client.get(f"{JOBS_URL}?q=Break").json()
        day = worker_client.get(f"{DAY_URL}?date={DAY.isoformat()}").json()

        offered = {each["id"] for each in jobs["jobs"]} | set(jobs["pinned_job_ids"])
        assert str(break_job.id) not in offered
        assert str(break_job.id) not in {each["id"] for each in searched["jobs"]}
        # On his day they travel as breaks, so nothing that reads his jobs sees them.
        assert {entry["job_id"] for entry in day["entries"]} == {str(job.id)}
        assert [each["paid"] for each in day["breaks"]] == [True, False, True]

    def test_the_jobs_response_orders_its_buttons_with_ids_it_carries(
        self, worker_client: Client, company: Company, superuser: Staff, worker: Staff, job: Job
    ) -> None:
        today = timezone.localdate()
        bench = make_job(company, superuser, name="Bench", status="special")
        archived = make_job(company, superuser, name="Long gone", status="archived")
        make_time_line(bench, worker, accounting_date=today)
        make_time_line(job, worker, accounting_date=today)
        make_time_line(archived, worker, accounting_date=today)

        body = worker_client.get(JOBS_URL).json()

        assert body["pinned_job_ids"] == [str(bench.id)]
        assert body["recent_job_ids"] == [str(job.id)]
