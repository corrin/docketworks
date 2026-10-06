"""Clocking in and out: the day's state, the refusals, and who may set whose times."""

from datetime import datetime, time, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import InvalidInputError
from apps.core.models import CompanyDefaults
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import attendance
from apps.timesheet.tests.conftest import WEEK_START, authenticated_client

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

DAY = WEEK_START
CLOCK_URL = "/api/timesheets/my-day/clock/"
TIMES_URL = "/api/timesheets/my-day/times/"
DAY_URL = "/api/job/workshop/timesheets/"
STANDARD_URL = "/api/timesheets/my-day/standard-hours/"


def _at(day_offset: int, hour: int, minute: int, second: int = 0) -> datetime:
    """A local moment on DAY or a day near it."""
    return datetime.combine(
        DAY + timedelta(days=day_offset),
        time(hour, minute, second),
        tzinfo=timezone.get_current_timezone(),
    )


class TestClockTaps:
    def test_clock_in_and_out_stamp_the_minute_the_caller_gives(self, worker: Staff) -> None:
        started = attendance.clock_in(worker, _at(0, 6, 31, 44))
        finished = attendance.clock_out(worker, _at(0, 15, 1, 59))

        assert started == {
            "state": "at_work",
            "clock_in": time(6, 31),
            "clock_out": None,
            "here_hours": None,
            "sent_late": False,
            "cautions": [],
        }
        assert finished["state"] == "clocked_out"
        assert finished["clock_out"] == time(15, 1)
        assert finished["here_hours"] == 8.5

    def test_second_clock_in_is_refused(self, worker: Staff) -> None:
        """A stray tap never reopens or restarts a day; the explicit controls do."""
        attendance.clock_in(worker, _at(0, 6, 30))
        with pytest.raises(attendance.ClockingRefusedError, match="already clocked in"):
            attendance.clock_in(worker, _at(0, 7, 0))

        attendance.clock_out(worker, _at(0, 15, 0))
        with pytest.raises(attendance.ClockingRefusedError, match="clock back in"):
            attendance.clock_in(worker, _at(0, 15, 5))

        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert (row.clock_in, row.clock_out) == (time(6, 30), time(15, 0))

    def test_clock_out_on_a_later_date_asks_for_the_time(self, worker: Staff) -> None:
        """Yesterday's open day is not stamped with today's time; it is named as pending."""
        attendance.clock_in(worker, _at(0, 16, 0))

        with pytest.raises(attendance.ClockingRefusedError, match="not clocked in today"):
            attendance.clock_out(worker, _at(1, 0, 20))

        assert AttendanceDay.objects.get(staff=worker, date=DAY).clock_out is None
        assert attendance.pending_day(worker, DAY + timedelta(days=1)) == {
            "date": DAY,
            "state": "at_work",
        }
        assert attendance.pending_day(worker, DAY) is None

    def test_a_finish_past_midnight_is_refused_in_words(self, worker: Staff) -> None:
        """Times of day cannot hold it, so the worker is told to ask the office."""
        attendance.clock_in(worker, _at(0, 16, 0))

        with pytest.raises(InvalidInputError, match="ask the office"):
            attendance.set_clock_times(worker, DAY, time(16, 0), time(0, 20), worker)

        assert AttendanceDay.objects.get(staff=worker, date=DAY).clock_out is None


class TestSetTimes:
    def test_reopening_clears_sent(self, worker: Staff) -> None:
        attendance.set_clock_times(worker, DAY, time(6, 30), time(15, 0), worker)
        AttendanceDay.objects.filter(staff=worker, date=DAY).update(submitted_at=_at(0, 15, 2))
        assert attendance.day_attendance(worker, DAY)["state"] == "sent"

        reopened = attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)

        assert reopened["state"] == "at_work"
        assert AttendanceDay.objects.get(staff=worker, date=DAY).submitted_at is None

    def test_worker_cannot_set_another_persons_times(
        self, worker_client: Client, other_worker: Staff, office_staff: Staff
    ) -> None:
        body = {
            "date": DAY.isoformat(),
            "clock_in": "06:30",
            "clock_out": "15:00",
            "staff_id": str(other_worker.id),
        }

        refused = worker_client.put(TIMES_URL, data=body, content_type="application/json")
        allowed = authenticated_client(office_staff).put(
            TIMES_URL, data=body, content_type="application/json"
        )

        assert refused.status_code == 403
        assert allowed.status_code == 200, allowed.content
        assert allowed.json()["here_hours"] == 8.5
        assert AttendanceDay.objects.get(staff=other_worker, date=DAY).clock_out == time(15, 0)

    def test_a_past_midnight_finish_answers_400_with_the_reason(
        self, worker_client: Client
    ) -> None:
        """The refusal reaches the phone as words, never as a constraint error."""
        response = worker_client.put(
            TIMES_URL,
            data={"date": DAY.isoformat(), "clock_in": "16:00", "clock_out": "00:20"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert "later than the start time (16:00)" in response.json()["detail"]


class TestDayState:
    def test_day_state_words(self, worker: Staff) -> None:
        assert attendance.day_attendance(worker, DAY)["state"] == "not_clocked_in"
        attendance.set_clock_times(worker, DAY, time(6, 30), None, worker)
        assert attendance.day_attendance(worker, DAY)["state"] == "at_work"
        attendance.set_clock_times(worker, DAY, time(6, 30), time(15, 0), worker)
        assert attendance.day_attendance(worker, DAY)["state"] == "clocked_out"
        AttendanceDay.objects.filter(staff=worker, date=DAY).update(submitted_at=_at(0, 15, 2))
        assert attendance.day_attendance(worker, DAY)["state"] == "sent"

    def test_a_day_sent_on_a_later_local_date_is_sent_late(self, worker: Staff) -> None:
        """Local dates, as for entries: 23:50 that night is on time, 00:10 is late."""
        attendance.set_clock_times(worker, DAY, time(6, 30), time(15, 0), worker)
        rows = AttendanceDay.objects.filter(staff=worker, date=DAY)

        rows.update(submitted_at=_at(0, 23, 50))
        assert attendance.day_attendance(worker, DAY)["sent_late"] is False
        rows.update(submitted_at=_at(1, 0, 10))
        assert attendance.day_attendance(worker, DAY)["sent_late"] is True

    def test_the_day_read_carries_the_clock_and_an_earlier_open_day(
        self, worker_client: Client, worker: Staff
    ) -> None:
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        attendance.set_clock_times(worker, yesterday, time(16, 0), None, worker)

        body = worker_client.get(f"{DAY_URL}?date={today.isoformat()}").json()

        assert body["day"]["state"] == "not_clocked_in"
        assert body["pending"] == {"date": yesterday.isoformat(), "state": "at_work"}

    def test_the_clock_tap_endpoint_uses_the_servers_time(self, worker_client: Client) -> None:
        started = worker_client.post(
            CLOCK_URL, data={"action": "in"}, content_type="application/json"
        )
        again = worker_client.post(
            CLOCK_URL, data={"action": "in"}, content_type="application/json"
        )

        assert started.status_code == 200, started.content
        assert started.json()["state"] == "at_work"
        assert again.status_code == 409


def _how(worker: Staff) -> tuple[str, str | None]:
    row = AttendanceDay.objects.get(staff=worker, date=DAY)
    return row.clock_in_how, row.clock_out_how


class TestHowAClockTimeGotThere:
    """A tap is the record that he was here; anything else is not, and the office is told."""

    def test_a_tap_is_clocked_and_an_edit_is_not(self, worker: Staff) -> None:
        attendance.clock_in(worker, _at(0, 6, 31))
        attendance.clock_out(worker, _at(0, 15, 1))
        assert _how(worker) == ("clocked", "clocked")
        assert attendance.day_attendance(worker, DAY)["cautions"] == []

        # He corrects his finish: the start he tapped is still a tap.
        attendance.set_clock_times(worker, DAY, time(6, 31), time(15, 30), worker)
        assert _how(worker) == ("clocked", "not_clocked")
        assert attendance.day_attendance(worker, DAY)["cautions"] == ["Did not clock out"]

        attendance.set_clock_times(worker, DAY, time(6, 0), time(15, 30), worker)
        assert _how(worker) == ("not_clocked", "not_clocked")

    def test_a_time_the_office_sets_raises_no_warning(
        self, worker: Staff, office_staff: Staff
    ) -> None:
        """Nobody is chased over the office's own entry or its tidying of a tap."""
        attendance.clock_in(worker, _at(0, 6, 31))
        attendance.clock_out(worker, _at(0, 15, 1))

        attendance.set_clock_times(worker, DAY, time(6, 30), time(15, 1), office_staff)

        assert _how(worker) == ("set_by_office", "clocked")
        assert attendance.day_attendance(worker, DAY)["cautions"] == []

    def test_standard_hours_come_from_the_weekdays_company_defaults(self) -> None:
        company = CompanyDefaults.get_solo()
        company.mon_start = time(6, 30)
        company.mon_end = time(15, 0)
        company.tue_start = time(8, 0)
        company.save(update_fields=["mon_start", "mon_end", "tue_start"])

        assert attendance.standard_day(DAY) == attendance.Window(time(6, 30), time(15, 0))
        tuesday = attendance.standard_day(DAY + timedelta(days=1))
        assert tuesday is not None and tuesday.start == time(8, 0)

    def test_a_weekend_has_no_standard_day(self, worker: Staff) -> None:
        saturday = DAY + timedelta(days=5)

        assert attendance.standard_day(saturday) is None
        with pytest.raises(InvalidInputError, match="no standard hours on a weekend"):
            attendance.use_standard_hours(worker, saturday, worker)

    def test_using_standard_hours_records_them_as_not_clocked_and_generates_breaks(
        self, worker_client: Client, worker: Staff
    ) -> None:
        company = CompanyDefaults.get_solo()
        company.mon_start = time(6, 30)
        company.save(update_fields=["mon_start"])

        response = worker_client.post(
            STANDARD_URL, data={"date": DAY.isoformat()}, content_type="application/json"
        )
        again = worker_client.post(
            STANDARD_URL, data={"date": DAY.isoformat()}, content_type="application/json"
        )

        assert response.status_code == 200, response.content
        assert response.json()["cautions"] == ["Did not clock in", "Did not clock out"]
        assert _how(worker) == ("not_clocked", "not_clocked")
        row = AttendanceDay.objects.get(staff=worker, date=DAY)
        assert (row.clock_in, row.clock_out) == (time(6, 30), time(15, 0))
        assert row.breaks_generated
        day = worker_client.get(f"{DAY_URL}?date={DAY.isoformat()}").json()
        assert day["fill"]["to_fill_hours"] == 8.0
        assert [each["paid"] for each in day["breaks"]] == [True, False, True]
        assert day["standard"] == {"start": "06:30:00", "end": "15:00:00"}
        assert again.status_code == 409

    def test_a_missed_clock_out_is_offered_the_standard_finish(self, worker: Staff) -> None:
        today = DAY + timedelta(days=1)
        attendance.clock_in(worker, _at(0, 6, 31))
        row = AttendanceDay.objects.get(staff=worker, date=DAY)

        assert attendance.missed_clock_out_finish(row, today) == time(15, 0)
        # Still today: he may yet tap out.
        assert attendance.missed_clock_out_finish(row, DAY) is None
        # He started after the standard finish: the finish is his to give.
        attendance.set_clock_times(worker, DAY, time(16, 0), None, worker)
        row.refresh_from_db()
        assert attendance.missed_clock_out_finish(row, today) is None

    def test_the_office_is_told_who_did_not_clock_in_or_out(
        self, worker: Staff, other_worker: Staff, office_staff: Staff
    ) -> None:
        attendance.use_standard_hours(worker, DAY, worker)
        attendance.clock_in(other_worker, _at(0, 6, 31))
        attendance.clock_out(other_worker, _at(0, 15, 1))

        body = (
            authenticated_client(office_staff)
            .get(f"/api/timesheets/approvals/?date={DAY.isoformat()}")
            .json()
        )

        cautions = {row["staff_id"]: row["clock"]["cautions"] for row in body["staff"]}
        assert cautions[str(worker.id)] == ["Did not clock in", "Did not clock out"]
        assert cautions[str(other_worker.id)] == []
        assert body["standard"] == {"start": "07:00:00", "end": "15:00:00"}
