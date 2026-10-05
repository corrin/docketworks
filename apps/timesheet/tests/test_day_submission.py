"""Filling and sending a day: the arithmetic, the layout, and all-or-nothing sending."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.errors import ConflictError, InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import attendance, day_submission, timesheet_entry_options
from apps.timesheet.services.attendance import LunchWindow
from apps.timesheet.tests.conftest import WEEK_START, make_leave_job, make_time_line

pytestmark = pytest.mark.django_db

DAY = WEEK_START
LUNCH = LunchWindow(time(11, 30), time(12, 0))
SUBMIT_URL = "/api/timesheets/my-day/submit/"
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


class TestHoursToFill:
    def test_span_deducts_the_lunch_line(self) -> None:
        assert attendance.paid_span_hours(time(6, 30), time(15, 0), None) == Decimal("8.5")
        assert attendance.paid_span_hours(time(6, 30), time(15, 0), LUNCH) == Decimal("8")

    def test_span_rounds_to_the_quarter_hour(self) -> None:
        """A real clock gives 06:28 to 15:04; the worker is never shown 8.1."""
        assert attendance.paid_span_hours(time(6, 28), time(15, 4), LUNCH) == Decimal("8")
        assert attendance.paid_span_hours(time(6, 30), time(15, 8), LUNCH) == Decimal("8.25")

    def test_to_go_is_what_is_left_and_goes_negative_when_over(self, worker: Staff) -> None:
        _clocked(worker)
        row = AttendanceDay.objects.get(staff=worker, date=DAY)

        assert attendance.fill_figures(row, LUNCH, Decimal("3")) == {
            "to_fill_hours": 8.0,
            "entered_hours": 3.0,
            "to_go_hours": 5.0,
        }
        over = attendance.fill_figures(row, LUNCH, Decimal("9"))
        assert over is not None and over["to_go_hours"] == -1.0

    def test_there_is_nothing_to_fill_until_both_clock_times_are_known(self, worker: Staff) -> None:
        assert attendance.fill_figures(None, None, Decimal("3")) is None
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)
        open_row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert attendance.fill_figures(open_row, None, Decimal("3")) is None


class TestLayout:
    def test_rows_are_laid_end_to_end_from_clock_in(self, job: Job) -> None:
        lines = day_submission.lay_out_rows(time(6, 30), [_row(job, "3"), _row(job, "1.25")], [])

        assert _spans(lines) == [
            ("06:30", "09:30", Decimal("3")),
            ("09:30", "10:45", Decimal("1.25")),
        ]

    def test_a_row_across_lunch_is_split(self, job: Job) -> None:
        lines = day_submission.lay_out_rows(
            time(6, 30), [_row(job, "3"), _row(job, "5")], [(LUNCH.start, LUNCH.end)]
        )

        assert _spans(lines) == [
            ("06:30", "09:30", Decimal("3")),
            ("09:30", "11:30", Decimal("2")),
            ("12:00", "15:00", Decimal("3")),
        ]
        assert {line["job_id"] for line in lines} == {job.id}

    def test_rows_skip_existing_timed_entries(self, job: Job) -> None:
        """What he already put on his calendar stays where it is; the rows go round it."""
        lines = day_submission.lay_out_rows(
            time(6, 30), [_row(job, "2")], [(time(6, 30), time(8, 0)), (time(9, 0), time(9, 30))]
        )

        assert _spans(lines) == [
            ("08:00", "09:00", Decimal("1")),
            ("09:30", "10:30", Decimal("1")),
        ]

    def test_hours_are_quarter_hours(self, job: Job) -> None:
        with pytest.raises(InvalidInputError, match="quarter hours"):
            day_submission.lay_out_rows(time(6, 30), [_row(job, "1.1")], [])


class TestSubmitDay:
    def test_rows_become_entries_and_the_day_is_sent(self, worker: Staff, job: Job) -> None:
        _clocked(worker)
        now = timezone.now()

        day = day_submission.submit_day(
            worker, DAY, [_row(job, "3"), _row(job, "2", time_and_a_half=True)], None, now
        )

        assert day["day"]["state"] == "sent"
        assert [(entry["start_time"], entry["end_time"]) for entry in day["entries"]] == [
            (time(6, 30), time(9, 30)),
            (time(9, 30), time(11, 30)),
        ]
        assert [entry["wage_rate_multiplier"] for entry in day["entries"]] == [1.0, 1.5]
        assert all(not entry["approved"] for entry in day["entries"])
        assert day["fill"] == {"to_fill_hours": 8.5, "entered_hours": 5.0, "to_go_hours": 3.5}

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

        assert not CostLine.objects.filter(staff=worker).exists()
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
        assert day["fill"] is not None and day["fill"]["to_go_hours"] == 8.5


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
    def test_the_calendar_opens_on_the_clocked_span_with_an_hour_either_side(
        self, worker: Staff
    ) -> None:
        _clocked(worker)
        row = AttendanceDay.objects.get(staff=worker, date=DAY)

        bounds = attendance.calendar_bounds(row, (time(7, 0), time(15, 0)), [])

        assert bounds == {"start": time(5, 0), "end": time(16, 0)}

    def test_it_falls_back_to_the_working_day_and_widens_for_entries(self) -> None:
        bounds = attendance.calendar_bounds(
            None, (time(7, 0), time(15, 0)), [(time(17, 0), time(18, 30))]
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
