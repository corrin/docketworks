"""Filling and sending a day: the arithmetic, the layout, and all-or-nothing sending."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

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
from apps.timesheet.models import AttendanceBreak, AttendanceDay
from apps.timesheet.services import (
    attendance,
    day_submission,
    timesheet_entry_options,
    weekly_timesheet_service,
)
from apps.timesheet.services.attendance import Window
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
    make_leave_job,
    make_time_line,
)

pytestmark = pytest.mark.django_db

DAY = WEEK_START
LUNCH = Window(time(11, 30), time(12, 0))
SUBMIT_URL = "/api/timesheets/my-day/submit/"
BREAKS_URL = "/api/timesheets/my-day/breaks/"
DAY_URL = "/api/job/workshop/timesheets/"
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
    def test_span_deducts_unpaid_breaks(self) -> None:
        assert attendance.paid_span_hours(time(6, 30), time(15, 0), []) == Decimal("8.5")
        assert attendance.paid_span_hours(time(6, 30), time(15, 0), [LUNCH]) == Decimal("8")

    def test_span_rounds_to_the_quarter_hour(self) -> None:
        """A real clock gives 06:28 to 15:04; the worker is never shown 8.1."""
        assert attendance.paid_span_hours(time(6, 28), time(15, 4), [LUNCH]) == Decimal("8")
        assert attendance.paid_span_hours(time(6, 30), time(15, 8), [LUNCH]) == Decimal("8.25")

    def test_to_go_is_what_is_left_and_goes_negative_when_over(self, worker: Staff) -> None:
        _clocked(worker)
        row = AttendanceDay.objects.get(staff=worker, date=DAY)

        assert attendance.fill_figures(row, Decimal("3")) == {
            "to_fill_hours": 8.0,
            "entered_hours": 3.0,
            "to_go_hours": 5.0,
        }
        over = attendance.fill_figures(row, Decimal("9"))
        assert over is not None and over["to_go_hours"] == -1.0

    def test_there_is_nothing_to_fill_until_both_clock_times_are_known(self, worker: Staff) -> None:
        assert attendance.fill_figures(None, Decimal("3")) is None
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)
        open_row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert attendance.fill_figures(open_row, Decimal("3")) is None


def _breaks(worker: Staff) -> list[tuple[str, str, bool]]:
    row = AttendanceDay.objects.get(staff=worker, date=DAY)
    return [
        (f"{each.start:%H:%M}", f"{each.end:%H:%M}", each.paid)
        for each in attendance.day_breaks(row)
    ]


class TestBreaks:
    """The day as a timeline to remember it by: started, a paid break, an unpaid one, finished."""

    def test_defaults_are_generated_once_when_the_span_covers_them(self, worker: Staff) -> None:
        _clocked(worker)

        assert _breaks(worker) == [
            ("08:30", "08:45", True),
            ("11:30", "12:00", False),
            ("13:30", "13:45", True),
        ]
        # The standard day: two paid breaks and an unpaid lunch leave 8 hours to fill.
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        figures = attendance.fill_figures(row, Decimal(0))
        assert figures is not None and figures["to_fill_hours"] == 8.0

    def test_a_short_span_gets_no_default_break(self, worker: Staff) -> None:
        """Gone by 11:45: he was there for the paid break and not for the whole of lunch."""
        _clocked(worker, time(6, 30), time(11, 45))

        assert _breaks(worker) == [("08:30", "08:45", True)]

    def test_correcting_clock_times_does_not_regenerate_breaks(self, worker: Staff) -> None:
        """He worked through lunch and said so; the office fixing his finish does not undo it."""
        _clocked(worker)
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        lunch = next(each for each in attendance.day_breaks(row) if not each.paid)
        attendance.remove_break(lunch.id, worker)

        _clocked(worker, time(6, 30), time(15, 30))

        assert _breaks(worker) == [("08:30", "08:45", True), ("13:30", "13:45", True)]

    def test_an_unpaid_break_comes_off_the_hours_to_fill_and_a_paid_one_does_not(
        self, worker: Staff
    ) -> None:
        _clocked(worker)
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        with_both = attendance.fill_figures(row, Decimal(0))
        for each in attendance.day_breaks(row):
            if each.paid:
                attendance.remove_break(each.id, worker)
        without_paid = attendance.fill_figures(row, Decimal(0))
        for each in attendance.day_breaks(row):
            attendance.remove_break(each.id, worker)
        without_any = attendance.fill_figures(row, Decimal(0))

        assert with_both is not None and with_both["to_fill_hours"] == 8.0
        assert without_paid == with_both
        assert without_any is not None and without_any["to_fill_hours"] == 8.5

    def test_a_break_outside_the_clocked_span_does_not_shrink_the_day(self, worker: Staff) -> None:
        """Moved to after he had gone: only the part inside his hours comes off."""
        _clocked(worker)
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        lunch = next(each for each in attendance.day_breaks(row) if not each.paid)

        attendance.change_break(lunch.id, time(14, 45), time(15, 15), worker)
        straddling = attendance.fill_figures(row, Decimal(0))
        attendance.change_break(lunch.id, time(16, 0), time(16, 30), worker)
        outside = attendance.fill_figures(row, Decimal(0))

        assert straddling is not None and straddling["to_fill_hours"] == 8.25
        assert outside is not None and outside["to_fill_hours"] == 8.5

    def test_rows_run_through_a_paid_break_and_around_an_unpaid_one(
        self, worker: Staff, job: Job
    ) -> None:
        _clocked(worker)

        day = day_submission.submit_day(
            worker, DAY, [_row(job, "3"), _row(job, "5")], None, timezone.now()
        )

        assert [(entry["start_time"], entry["end_time"]) for entry in day["entries"]] == [
            (time(6, 30), time(9, 30)),
            (time(9, 30), time(11, 30)),
            (time(12, 0), time(15, 0)),
        ]
        assert day["fill"] == {"to_fill_hours": 8.0, "entered_hours": 8.0, "to_go_hours": 0.0}

    def test_moving_a_break_moves_nothing_else_and_leaves_the_day_sent(
        self, worker: Staff, job: Job
    ) -> None:
        _clocked(worker)
        day_submission.submit_day(worker, DAY, [_row(job, "3")], None, timezone.now())
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        lunch = next(each for each in attendance.day_breaks(row) if not each.paid)

        attendance.change_break(lunch.id, time(7, 0), time(7, 30), worker)

        line = CostLine.objects.get(staff=worker)
        assert (line.meta["start_time"], line.meta["end_time"]) == ("06:30:00", "09:30:00")
        assert attendance.day_attendance(worker, DAY)["state"] == "sent"

    def test_a_worker_cannot_change_another_persons_break(
        self, worker_client: Client, other_worker: Staff, office_staff: Staff
    ) -> None:
        attendance.set_clock_times(other_worker, DAY, time(6, 30), time(15, 0), other_worker)
        theirs = AttendanceBreak.objects.filter(attendance_day__staff=other_worker).first()
        assert theirs is not None
        url = f"{BREAKS_URL}{theirs.id}/"
        body = {"start": "10:00", "end": "10:15"}

        moved = worker_client.put(url, data=body, content_type="application/json")
        removed = worker_client.delete(url)
        added = worker_client.post(
            BREAKS_URL,
            data={
                "date": DAY.isoformat(),
                "start": "13:00",
                "end": "13:15",
                "paid": True,
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
        assert theirs.start == time(10, 0)
        assert AttendanceBreak.objects.filter(attendance_day__staff=other_worker).count() == 3

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

    def test_breaks_never_appear_in_time_or_pay_figures(
        self, worker_client: Client, worker: Staff, job: Job
    ) -> None:
        """Breaks belong to the day, not to job costing: no daily or weekly figure moves.

        The week's posted lines are held to the same in apps/xero/tests/test_payroll_push.py,
        since this app may not import the payroll push.
        """
        make_time_line(job, worker, accounting_date=DAY, hours="5.000")
        make_time_line(job, worker, accounting_date=DAY, hours="3.000", approved=False)

        def figures() -> tuple[object, object, object]:
            day = worker_client.get(f"{DAY_URL}?date={DAY.isoformat()}").json()
            [week_row] = [
                row
                for row in weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]
                if row["staff_id"] == str(worker.id)
            ]
            return day["summary"], day["week"], week_row

        without_breaks = figures()
        _clocked(worker)
        assert len(_breaks(worker)) == 3

        assert figures() == without_breaks


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
        assert day["fill"] == {"to_fill_hours": 8.0, "entered_hours": 5.0, "to_go_hours": 3.0}

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
        assert day["fill"] is not None and day["fill"]["to_go_hours"] == 8.0


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
