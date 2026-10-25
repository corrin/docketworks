# ruff: noqa: N802 -- tests are named by the plan's scenario ids (A3, R6, V1)
"""Whole days at a six-person shop, as the office sweeps and approves them (owner, 2026-10-25).

Sections A, B, D, G, R and V of the timesheet scenario list. Every day is set up
through the services the screens call; every expected figure is worked out by
hand from the company defaults: the usual day 07:00-15:00, paid breaks
08:30-08:45 and 13:30-13:45, unpaid lunch 11:30-12:00. A full standard day is
7h on jobs plus 0.5h of paid breaks: 7.5h paid. His wage is 48.00 an hour
(40.00 + 20% loading) and the customer job charges 120.00.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import is_unpaid_time
from apps.timesheet.models import AttendanceDay, LeaveType
from apps.timesheet.services import approval, attendance, leave_service, workshop_timesheet_service
from apps.timesheet.services.approval import StaffApprovalData
from apps.timesheet.services.workshop_timesheet_service import WorkshopEntryCreateData
from apps.timesheet.tests import test_approval
from apps.timesheet.tests.conftest import (
    WEEK_START,
    make_leave_job,
    make_public_holiday_job,
    make_staff,
    make_time_line,
)
from apps.timesheet.tests.test_hours_and_overtime import _break_at

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

#: The one General work fixture (ADR 0039), registered in this module by name.
general_work = test_approval.general_work

DAY = WEEK_START  # Monday 2026-05-04, a day gone by.

#: A line on a job: start, stop, hours and wage multiplier.
Line = tuple[str, str, Decimal, float]


# ── Setting the day up, as the screens do ─────────────────────────────


def _at(day: date, moment: str) -> datetime:
    """A local moment on ``day``, as a phone taps it."""
    return datetime.combine(day, time.fromisoformat(moment), tzinfo=timezone.get_current_timezone())


def _clock(person: Staff, start: str, finish: str, *, by: Staff | None = None) -> None:
    """Set his day's clock times by hand: his own, unless the office sets them."""
    attendance.set_clock_times(
        person,
        DAY,
        time.fromisoformat(start),
        time.fromisoformat(finish),
        person if by is None else by,
    )


def _enter(  # noqa: PLR0913, PLR0917 -- who saves it, whose it is, the job, the hours and two times
    by: Staff,
    owner: Staff,
    job: Job,
    hours: str,
    start: str | None = None,
    end: str | None = None,
) -> None:
    """Save an entry as the drawer does; without times it is placed after his latest."""
    data: WorkshopEntryCreateData = {
        "job_id": job.id,
        "accounting_date": DAY,
        "hours": Decimal(hours),
    }
    if start is not None and end is not None:
        data["start_time"] = time.fromisoformat(start)
        data["end_time"] = time.fromisoformat(end)
    workshop_timesheet_service.create_entry(by, owner, data)


#: A whole day's leave hours: the roster's 8h for a weekday.
WHOLE_DAY = Decimal("8")


def _leave(
    person: Staff, code: str, actor: Staff, *, start: date = DAY, end: date = DAY
) -> leave_service.SaveResult:
    """Book whole days of leave for him from the office's leave screen.

    Leave is booked in whole days (owner, 2026-10-25). Opus: RequestedDay still
    carries an hours figure, so each day asks for its full 8h; the service puts
    to leave only the day's leave hours less the paid hours already on it.
    """
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    return leave_service.create_leave_request(
        staff_id=person.id,
        leave_type_code=code,
        start_date=start,
        end_date=end,
        note=None,
        requested_days=[{"date": each, "hours": WHOLE_DAY} for each in days],
        actor=actor,
    )


def _leave_warning(person: Staff, day: date, put_to_leave: str) -> str:
    """The office's warning that leave was booked on a day that already had time."""
    return (
        f"Leave booked for {person.first_name} on {day.isoformat()}, but the day "
        f"already had time entered: {put_to_leave} put to leave."
    )


def _second_job(company: Company, superuser: Staff) -> Job:
    """Another customer job, charging the same 120.00 as the first."""
    job = make_job(company, superuser, name="Second Job")
    job.labour_rates.filter(labour_subtype=LabourSubtype.default_workshop()).update(
        charge_out_rate=Decimal("120.00")
    )
    return job


# ── Reading the outcome back ───────────────────────────────────────────


def _day_lines(person: Staff, day: date = DAY) -> list[CostLine]:
    return list(
        CostLine.objects.filter(
            cost_set__kind="actual", kind="time", staff=person, accounting_date=day
        ).select_related("xero_pay_item")
    )


def _on(job: Job, person: Staff, day: date = DAY) -> list[Line]:
    """His lines on the job that day, in the order of the day."""
    return sorted(
        (
            line.meta["start_time"],
            line.meta["end_time"],
            line.quantity,
            line.meta["wage_rate_multiplier"],
        )
        for line in CostLine.objects.filter(
            staff=person, cost_set__job=job, accounting_date=day, kind="time"
        )
    )


def _paid(person: Staff, day: date = DAY) -> Decimal:
    """Hours he is paid for the day: every line but lunch and other unpaid breaks."""
    return sum(
        (line.quantity for line in _day_lines(person, day) if not is_unpaid_time(line)),
        Decimal(0),
    )


def _leave_hours(person: Staff, day: date = DAY) -> Decimal:
    """His hours on leave that day; none when nothing was put to leave."""
    return sum(
        (line.quantity for line in _day_lines(person, day) if line.managed_by == "leave"),
        Decimal(0),
    )


def _billed(person: Staff, day: date = DAY) -> Decimal:
    """What his day charges customers: hours times the charge on each line."""
    return sum((line.quantity * line.unit_rev for line in _day_lines(person, day)), Decimal(0))


def _all_approved(person: Staff, day: date = DAY) -> bool:
    lines = _day_lines(person, day)
    return bool(lines) and all(line.approved for line in lines)


def _row(person: Staff) -> StaffApprovalData:
    """His row on Approve time for DAY."""
    [row] = [
        row for row in approval.day_approvals(DAY)["staff"] if row["staff_id"] == str(person.id)
    ]
    return row


def _overtime_warning(person: Staff) -> dict[str, str]:
    """The sweep's word to the office that his day went past the usual 8h (owner, 2026-10-25).

    The message names him as the screens do, by his first name: "Joe has done
    over 8h". 8h is the usual day, 07:00 to 15:00.
    """
    return {
        "staff_id": str(person.id),
        "staff_name": f"{person.first_name} {person.last_name}",
        "message": f"{person.first_name} has done over 8h, converting some time to overtime.",
    }


#: General work for a whole standard day: the stretches between the three breaks.
STANDARD_GENERAL_WORK: list[Line] = [
    ("07:00:00", "08:30:00", Decimal("1.5"), 1.0),
    ("08:45:00", "11:30:00", Decimal("2.75"), 1.0),
    ("12:00:00", "13:30:00", Decimal("1.5"), 1.0),
    ("13:45:00", "15:00:00", Decimal("1.25"), 1.0),
]


# ── A. Nobody fills in anything ────────────────────────────────────────


@pytest.mark.usefixtures("general_work")
class TestNobodyFillsInAnything:
    def test_A1_rostered_unclocked_and_empty_is_swept_as_the_standard_day(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """Rostered, he never clocked and entered nothing; the office sweeps the day.

        Guards approval._sweep (the assumed standard day) and
        attendance.unallocated_windows (the stretches around the standard breaks).
        """
        result = approval.sweep_person(worker, [DAY], office_staff)

        # 1.5 + 2.75 + 1.5 + 1.25 = 7h of General work; the breaks and General
        # work are the office's, approved as saved, so nothing else is approved.
        assert result == {"swept_hours": 7.0, "approved_count": 0, "skipped": [], "overtime": []}
        assert _on(general_work, worker) == STANDARD_GENERAL_WORK
        # 7h + two 0.25h paid breaks.
        assert _paid(worker) == Decimal("7.5")
        assert _billed(worker) == Decimal(0)
        assert _all_approved(worker)

    def test_A2_clocked_the_standard_day_and_empty_is_swept_from_his_clock(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """He clocked 07:00-15:00 and entered nothing; the office sweeps the day.

        Guards approval._sweep and attendance.unallocated_windows on a clocked day.
        """
        _clock(worker, "07:00", "15:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # His own three breaks were waiting, and are approved with the day.
        assert result == {"swept_hours": 7.0, "approved_count": 3, "skipped": [], "overtime": []}
        assert _on(general_work, worker) == STANDARD_GENERAL_WORK
        assert _paid(worker) == Decimal("7.5")
        assert _billed(worker) == Decimal(0)
        assert _all_approved(worker)

    def test_A3_ten_clocked_hours_swept_are_eight_ordinary_then_overtime(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """He clocked 07:00-17:00 and entered nothing; the office sweeps the day.

        Guards workshop_timesheet_service.overtime_hours and _split_at_overtime as
        the sweep's General work reaches them through create_entry.
        """
        _clock(worker, "07:00", "17:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # Stretches 1.5 + 2.75 + 1.5 + 3.25 = 9h. After the first three, 5.75h
        # are worked, so the last stretch has 8 - 5.75 = 2.25h ordinary
        # (13:45 to 16:00) and 1h at time and a half (16:00 to 17:00).
        assert result == {
            "swept_hours": 9.0,
            "approved_count": 3,
            "skipped": [],
            "overtime": [_overtime_warning(worker)],
        }
        assert _on(general_work, worker) == [
            *STANDARD_GENERAL_WORK[:3],
            ("13:45:00", "16:00:00", Decimal("2.25"), 1.0),
            ("16:00:00", "17:00:00", Decimal("1"), 1.5),
        ]
        late = CostLine.objects.get(staff=worker, meta__start_time="16:00:00")
        # Paid 48.00 x 1.5 = 72.00; a shop job charges nobody.
        assert (late.unit_cost, late.unit_rev) == (Decimal("72.00"), Decimal("0.00"))
        # 9h of General work + 0.5h paid breaks.
        assert _paid(worker) == Decimal("9.5")
        assert _billed(worker) == Decimal(0)

    def test_A9_the_sweep_warns_the_office_when_it_takes_a_day_past_eight_hours(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Joe clocked 07:00-17:00 with a 2h job entered at 07:00; the office sweeps.

        Guards approval._sweep's overtime warning and the General work it splits
        through workshop_timesheet_service.overtime_hours.
        """
        _clock(worker, "07:00", "17:00")
        _enter(worker, worker, job, "2")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # 2h from 07:00 over the 08:30 break ends 09:15.
        assert _on(job, worker) == [("07:00:00", "09:15:00", Decimal("2"), 1.0)]
        # Stretches 09:15-11:30 2.25 + 1.5 + 13:45-17:00 3.25 = 7h. Before the
        # last, 2 + 2.25 + 1.5 = 5.75h are worked: 2.25h ordinary to 16:00,
        # then 1h at time and a half.
        assert _on(general_work, worker) == [
            ("09:15:00", "11:30:00", Decimal("2.25"), 1.0),
            STANDARD_GENERAL_WORK[2],
            ("13:45:00", "16:00:00", Decimal("2.25"), 1.0),
            ("16:00:00", "17:00:00", Decimal("1"), 1.5),
        ]
        # His entry and his three breaks were waiting.
        assert result == {
            "swept_hours": 7.0,
            "approved_count": 4,
            "skipped": [],
            "overtime": [_overtime_warning(worker)],
        }
        # 2 + 7 + 0.5 paid breaks.
        assert _paid(worker) == Decimal("9.5")

    def test_A5_a_part_timer_on_his_day_off_is_not_swept(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """A part-timer not rostered on Mondays; the office sweeps everyone.

        Guards approval._people_on and approval._rostered: no roster, no assumed day.
        """
        part_timer = make_staff(
            "part.timer@example.com",
            first_name="Pat",
            last_name="Parttime",
            hours_mon=Decimal("0.00"),
        )

        result = approval.sweep_everyone([DAY], office_staff)

        # Only the rostered worker's standard 7h moves; the part-timer is not listed.
        assert result == {"swept_hours": 7.0, "approved_count": 0, "skipped": [], "overtime": []}
        assert _day_lines(part_timer) == []
        assert not AttendanceDay.objects.filter(staff=part_timer, date=DAY).exists()
        assert _on(general_work, worker) == STANDARD_GENERAL_WORK

    def test_A8_six_people_swept_for_a_week_are_booked_once(
        self, office_staff: Staff, general_work: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """All six are swept at once for a week, then swept again.

        Guards approval._sweep: a second sweep finds every stretch booked and pays
        nothing twice.
        """
        people = [
            worker,
            other_worker,
            *(make_staff(f"shop{n}@example.com", first_name=f"Shop{n}") for n in range(4)),
        ]
        week = approval.sweep_days(DAY, DAY + timedelta(days=6))

        first = approval.sweep_everyone(week, office_staff)
        lines_after_first = CostLine.objects.filter(kind="time").count()
        second = approval.sweep_everyone(week, office_staff)

        # 6 people x 5 weekdays x 7h; the weekend nobody is rostered for.
        assert first == {"swept_hours": 210.0, "approved_count": 0, "skipped": [], "overtime": []}
        assert second == {"swept_hours": 0.0, "approved_count": 0, "skipped": [], "overtime": []}
        assert CostLine.objects.filter(kind="time").count() == lines_after_first
        for person in people:
            for offset in range(5):
                assert _on(general_work, person, DAY + timedelta(days=offset)) == (
                    STANDARD_GENERAL_WORK
                )
            # 5 days x 7.5h paid.
            week_paid = sum((_paid(person, day) for day in week), Decimal(0))
            assert week_paid == Decimal("37.5")


# ── B. Someone enters some of the time, not all ────────────────────────


@pytest.mark.usefixtures("general_work")
class TestSomeOfTheTimeEntered:
    def test_B1_three_hours_from_seven_and_the_sweep_fills_the_rest(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Clocked 07:00-15:00, he entered 3h on Job X; the office sweeps the day.

        Guards attendance.unallocated_windows: General work fills only around his
        entry and his breaks.
        """
        _clock(worker, "07:00", "15:00")
        _enter(worker, worker, job, "3")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # 3h from 07:00 steps over the 08:30 break: 1.5h to 08:30, 1.5h from 08:45 to 10:15.
        assert _on(job, worker) == [("07:00:00", "10:15:00", Decimal("3"), 1.0)]
        # 10:15-11:30 1.25 + 12:00-13:30 1.5 + 13:45-15:00 1.25 = 4h.
        assert _on(general_work, worker) == [
            ("10:15:00", "11:30:00", Decimal("1.25"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        # His entry and his three breaks.
        assert result == {"swept_hours": 4.0, "approved_count": 4, "skipped": [], "overtime": []}
        # 3h x 120.00 = 360.00 billed; 3 + 4 + 0.5 = 7.5h paid.
        assert _billed(worker) == Decimal("360")
        assert _paid(worker) == Decimal("7.5")
        assert _all_approved(worker)

    def test_B2_untimed_hours_on_an_unclocked_day_are_placed_from_seven(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """He never clocked and entered 3h with no times; the office sweeps the day.

        Guards workshop_timesheet_service._placed (from the standard start, around
        the planned breaks) and approval._sweep's standard day.
        """
        _enter(worker, worker, job, "3")

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _on(job, worker) == [("07:00:00", "10:15:00", Decimal("3"), 1.0)]
        assert _on(general_work, worker) == [
            ("10:15:00", "11:30:00", Decimal("1.25"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        # Only his entry waited: the breaks are the office's.
        assert result == {"swept_hours": 4.0, "approved_count": 1, "skipped": [], "overtime": []}
        assert _paid(worker) == Decimal("7.5")
        assert _billed(worker) == Decimal("360")

    def test_B3_more_on_jobs_than_clocked_adds_nothing_and_is_approved(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """Clocked 07:00-15:00, he entered 9h on jobs; the office sweeps the day.

        Guards approval._put_on_general_work (no stretch, no negative entry) and
        approval._staff_day's "Over by" caution.
        """
        _clock(worker, "07:00", "15:00")
        _enter(worker, worker, job, "9")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # 9h from 07:00 around the three breaks ends 17:00; the 8 ordinary hours
        # end at 16:00, and the hour past them is time and a half.
        assert _on(job, worker) == [
            ("07:00:00", "16:00:00", Decimal("8"), 1.0),
            ("16:00:00", "17:00:00", Decimal("1"), 1.5),
        ]
        assert _on(general_work, worker) == []
        # Two job lines and three breaks.
        assert result == {"swept_hours": 0.0, "approved_count": 5, "skipped": [], "overtime": []}
        assert _all_approved(worker)
        # 9h + 0.5h paid breaks.
        assert _paid(worker) == Decimal("9.5")
        # To fill: 8h less lunch = 7.5; less 0.5 breaks and 9 entered = -2: over by 2h.
        assert _row(worker)["clock"]["cautions"] == [
            "Did not clock in",
            "Did not clock out",
            "Over by 2h",
        ]

    def test_B4_two_overlapping_entries_are_both_billed_and_paid(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, leave set-up and people
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        job: Job,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """He did two things at once: Job X and Job Y both 09:00-10:00; swept.

        Guards attendance._merged inside unallocated_windows: the overlap is one
        occupied stretch, so the sweep books around it once.
        """
        second = _second_job(company, superuser)
        _clock(worker, "07:00", "15:00")
        _enter(worker, worker, job, "1", "09:00", "10:00")
        _enter(worker, worker, second, "1", "09:00", "10:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _on(job, worker) == [("09:00:00", "10:00:00", Decimal("1"), 1.0)]
        assert _on(second, worker) == [("09:00:00", "10:00:00", Decimal("1"), 1.0)]
        # 1.5 + 0.25 + 1.5 + 1.5 + 1.25 = 6h; with the 2h on jobs exactly 8, so
        # nothing reaches time and a half.
        assert _on(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.5"), 1.0),
            ("08:45:00", "09:00:00", Decimal("0.25"), 1.0),
            ("10:00:00", "11:30:00", Decimal("1.5"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        assert result == {"swept_hours": 6.0, "approved_count": 5, "skipped": [], "overtime": []}
        # Each job billed 1h x 120.00; paid 2 + 6 + 0.5.
        assert _billed(worker) == Decimal("240")
        assert _paid(worker) == Decimal("8.5")

    def test_B5_a_booked_hour_over_the_morning_break_keeps_it_and_skips_the_break(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """On an unclocked day he entered 08:00-09:00 as a whole hour; the office sweeps.

        The standard breaks go only on the free part of the day (owner,
        2026-10-25): 1h is more than 60 - 15 minutes, so his hour has no room
        for the 08:30 break and it is skipped; lunch and 13:30 are recorded.
        Guards attendance.generate_default_breaks' skip of a break inside a full
        entry, and that recording breaks never changes an entry.
        """
        _enter(worker, worker, job, "1", "08:00", "09:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _on(job, worker) == [("08:00:00", "09:00:00", Decimal("1"), 1.0)]
        breaks = workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        assert [(each["start"], each["end"], each["paid"]) for each in breaks] == [
            (time(11, 30), time(12, 0), False),
            (time(13, 30), time(13, 45), True),
        ]
        # 07:00-08:00 1 + 09:00-11:30 2.5 + 12:00-13:30 1.5 + 13:45-15:00 1.25 = 6.25h.
        assert _on(general_work, worker) == [
            ("07:00:00", "08:00:00", Decimal("1"), 1.0),
            ("09:00:00", "11:30:00", Decimal("2.5"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        assert result == {"swept_hours": 6.25, "approved_count": 1, "skipped": [], "overtime": []}
        # 1 x 120.00 billed; paid 1 + 6.25 + the 0.25 afternoon break = 7.5,
        # 08:00-09:00 once.
        assert _billed(worker) == Decimal("120")
        assert _paid(worker) == Decimal("7.5")

    def test_B7_two_booked_hours_over_the_morning_break_skip_it(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """On an unclocked day he entered 08:00-10:00 as 2h; the office sweeps.

        The owner's example: 2h is more than 120 - 15 minutes, so the 08:30
        break is skipped; lunch and the 13:30 break are recorded and General
        work fills around them.
        Guards attendance.generate_default_breaks' skip of a break inside a full entry.
        """
        _enter(worker, worker, job, "2", "08:00", "10:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _on(job, worker) == [("08:00:00", "10:00:00", Decimal("2"), 1.0)]
        breaks = workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        assert [(each["start"], each["end"], each["paid"]) for each in breaks] == [
            (time(11, 30), time(12, 0), False),
            (time(13, 30), time(13, 45), True),
        ]
        # 07:00-08:00 1 + 10:00-11:30 1.5 + 12:00-13:30 1.5 + 13:45-15:00 1.25 = 5.25h.
        assert _on(general_work, worker) == [
            ("07:00:00", "08:00:00", Decimal("1"), 1.0),
            ("10:00:00", "11:30:00", Decimal("1.5"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        assert result == {"swept_hours": 5.25, "approved_count": 1, "skipped": [], "overtime": []}
        # 2 x 120.00 billed; paid 2 + 5.25 + 0.25 = 7.5.
        assert _billed(worker) == Decimal("240")
        assert _paid(worker) == Decimal("7.5")

    def test_B6_an_entry_past_his_clock_out_stands_and_the_sweep_warns_of_overtime(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """He entered Job X 14:00-18:00 but clocked out at 15:00; swept.

        Overtime goes in save order (owner, 2026-10-25): his job was saved first,
        so the morning General work past 8h is what comes out at 1.5x, and the
        sweep tells the office.
        Guards attendance.unallocated_windows (nothing after his clock-out),
        workshop_timesheet_service.overtime_hours as the sweep reaches it, and
        approval._sweep's overtime warning.
        """
        _clock(worker, "07:00", "15:00")
        _enter(worker, worker, job, "4", "14:00", "18:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # No break inside 14:00-18:00: the 4h stand as entered.
        assert _on(job, worker) == [("14:00:00", "18:00:00", Decimal("4"), 1.0)]
        # Stretches in save order, 4h already worked:
        #   07:00-08:30 1.5 -> 5.5 worked, all ordinary;
        #   08:45-11:30 2.75 -> 8 - 5.5 = 2.5 ordinary (08:45-11:15), 0.25 at 1.5x;
        #   12:00-13:30 1.5 and 13:45-14:00 0.25 -> past 8, all at 1.5x.
        assert _on(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.5"), 1.0),
            ("08:45:00", "11:15:00", Decimal("2.5"), 1.0),
            ("11:15:00", "11:30:00", Decimal("0.25"), 1.5),
            ("12:00:00", "13:30:00", Decimal("1.5"), 1.5),
            ("13:45:00", "14:00:00", Decimal("0.25"), 1.5),
        ]
        # 1.5 + 2.75 + 1.5 + 0.25 = 6h swept; his entry and three breaks approved.
        assert result == {
            "swept_hours": 6.0,
            "approved_count": 4,
            "skipped": [],
            "overtime": [_overtime_warning(worker)],
        }
        overtime = CostLine.objects.filter(
            staff=worker, cost_set__job=general_work, meta__wage_rate_multiplier=1.5
        )
        # 0.25 + 1.5 + 0.25 = 2h at 48.00 x 1.5 = 72.00, charged nothing.
        assert {(line.unit_cost, line.unit_rev) for line in overtime} == {
            (Decimal("72.00"), Decimal("0.00"))
        }
        # 4 + 6 + 0.5 paid breaks.
        assert _paid(worker) == Decimal("10.5")
        # To fill 7.5, less 0.5 breaks and 10 entered = -3: over by 3h.
        assert _row(worker)["clock"]["cautions"][-1] == "Over by 3h"


# ── D. Some people enter time, some don't ──────────────────────────────


@pytest.mark.usefixtures("general_work")
class TestSomeEnterSomeDont:
    def test_D1_six_people_four_ways_swept_at_once(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, leave set-up and people
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        job: Job,
        general_work: Job,
        worker: Staff,
        other_worker: Staff,
    ) -> None:
        """Two entered everything, two entered some, one nothing, one is on leave;
        the office sweeps everyone.

        Guards approval._sweep and approval._assumed_standard across one day's people.
        """
        make_leave_job(company, superuser, "Annual Leave")
        full = [worker, other_worker]
        partial = [make_staff(f"partial{n}@example.com", first_name=f"Part{n}") for n in range(2)]
        nothing = make_staff("nothing@example.com", first_name="Nothing")
        away = make_staff("away@example.com", first_name="Away")
        for person in full:
            _clock(person, "07:00", "15:00")
            _enter(person, person, job, "7")
        for person in partial:
            _clock(person, "07:00", "15:00")
            _enter(person, person, job, "3")
        # A whole day on a day with nothing on it: all 8h, no warning.
        assert _leave(away, LeaveType.Code.ANNUAL, superuser)["warnings"] == []

        result = approval.sweep_everyone([DAY], office_staff)

        for person in full:
            # 7h from 07:00 around the breaks ends 15:00: nothing to add.
            assert _on(job, person) == [("07:00:00", "15:00:00", Decimal("7"), 1.0)]
            assert _on(general_work, person) == []
        for person in partial:
            assert _on(general_work, person) == [
                ("10:15:00", "11:30:00", Decimal("1.25"), 1.0),
                *STANDARD_GENERAL_WORK[2:],
            ]
        assert _on(general_work, nothing) == STANDARD_GENERAL_WORK
        [leave_line] = _day_lines(away)
        assert (leave_line.quantity, leave_line.approved) == (Decimal("8"), True)
        assert not AttendanceDay.objects.filter(staff=away, date=DAY).exists()
        # 4 + 4 + 7 swept; each clocked person's entry and three breaks approved.
        assert result["swept_hours"] == 15.0
        assert result["approved_count"] == 16
        assert [(skip["staff_id"], skip["reason"]) for skip in result["skipped"]] == [
            (str(away.id), "no_clock_times")
        ]
        for person in [*full, *partial, nothing]:
            assert _paid(person) == Decimal("7.5")

    def test_D2_approving_one_persons_day_approves_only_his(
        self, office_staff: Staff, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        """Both put time in; the office approves one person's day.

        Guards approval.approve_day and approval._waiting: the person and the day only.
        """
        _enter(worker, worker, job, "3")
        _enter(other_worker, other_worker, job, "2")

        assert approval.approve_day(worker, DAY, office_staff) == 1

        assert _all_approved(worker)
        assert [line.approved for line in _day_lines(other_worker)] == [False]
        assert _row(worker)["state"] == "nothing_waiting"
        assert (_row(other_worker)["state"], _row(other_worker)["waiting_hours"]) == (
            "waiting",
            2.0,
        )


# ── G. Part days ───────────────────────────────────────────────────────


@pytest.mark.usefixtures("general_work")
class TestPartDays:
    def test_G1_half_day_leave_and_half_day_worked(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, leave set-up and people
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        job: Job,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """He worked the morning, 3.75h on Job X; the office books a day of annual
        leave, which fills the afternoon; the day is swept.

        Guards leave_service.create_leave_request (the fill and its warning),
        workshop_timesheet_service.overtime_hours (leave is not work) and
        attendance.unallocated_windows (leave takes none of his clocked time).
        """
        make_leave_job(company, superuser, "Annual Leave")
        _clock(worker, "07:00", "11:00")
        _enter(worker, worker, job, "3.75")

        booked = _leave(worker, LeaveType.Code.ANNUAL, superuser)
        result = approval.sweep_person(worker, [DAY], office_staff)

        # 3.75h from 07:00 over the 08:30 break ends 11:00, all ordinary.
        assert _on(job, worker) == [("07:00:00", "11:00:00", Decimal("3.75"), 1.0)]
        assert _on(general_work, worker) == []
        # His entry and his paid break; lunch was after he left.
        assert result == {"swept_hours": 0.0, "approved_count": 2, "skipped": [], "overtime": []}
        # 8 less 3.75 on the job and the 0.25 paid break = 4h to leave.
        assert booked["warnings"] == [_leave_warning(worker, DAY, "4h")]
        [leave_line] = [line for line in _day_lines(worker) if line.managed_by == "leave"]
        assert leave_line.quantity == Decimal("4")
        assert leave_line.xero_pay_item is not None
        assert leave_line.xero_pay_item.uses_leave_api
        # 3.75 + 0.25 + 4.
        assert _paid(worker) == Decimal("8")

    def test_G2_left_at_noon_drops_the_afternoon_break_and_sweeps_to_noon(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """He clocked in at 07:00 and out at 12:00; the office sweeps the day.

        Guards attendance.drop_breaks_after_finish and unallocated_windows' finish.
        """
        attendance.clock_in(worker, _at(DAY, "07:00"))
        attendance.clock_out(worker, _at(DAY, "12:00"))

        result = approval.sweep_person(worker, [DAY], office_staff)

        breaks = workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        assert [(each["start"], each["end"], each["paid"]) for each in breaks] == [
            (time(8, 30), time(8, 45), True),
            (time(11, 30), time(12, 0), False),
        ]
        # 07:00-08:30 1.5 + 08:45-11:30 2.75 = 4.25h.
        assert _on(general_work, worker) == STANDARD_GENERAL_WORK[:2]
        assert result == {"swept_hours": 4.25, "approved_count": 2, "skipped": [], "overtime": []}
        # 4.25 + the 0.25 paid break.
        assert _paid(worker) == Decimal("4.5")

    def test_G3_started_at_ten_has_no_morning_break_and_is_swept_from_ten(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """He clocked in at 10:00 and out at 15:00; the office sweeps the day.

        Guards attendance.generate_default_breaks: no break before his start.
        """
        attendance.clock_in(worker, _at(DAY, "10:00"))
        attendance.clock_out(worker, _at(DAY, "15:00"))

        result = approval.sweep_person(worker, [DAY], office_staff)

        breaks = workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
        assert [each["start"] for each in breaks] == [time(11, 30), time(13, 30)]
        # 10:00-11:30 1.5 + 12:00-13:30 1.5 + 13:45-15:00 1.25 = 4.25h.
        assert _on(general_work, worker) == [
            ("10:00:00", "11:30:00", Decimal("1.5"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        assert result == {"swept_hours": 4.25, "approved_count": 2, "skipped": [], "overtime": []}
        assert _paid(worker) == Decimal("4.5")

    def test_G4_an_office_closure_is_holiday_for_everyone_and_never_swept(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, leave set-up and people
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
        other_worker: Staff,
    ) -> None:
        """The office closes for a public holiday, then sweeps everyone.

        Guards leave_service.create_office_closure (no pay item, so Xero pays it
        alone) and approval._assumed_standard (a day with leave is not assumed).
        """
        holiday = make_public_holiday_job(company, superuser)
        leave_service.create_office_closure(
            start_date=DAY, end_date=DAY, note="Office closed", actor=superuser
        )

        result = approval.sweep_everyone([DAY], office_staff)

        for person in (worker, other_worker):
            [line] = _day_lines(person)
            assert line.cost_set.job_id == holiday.id
            assert (line.quantity, line.xero_pay_item_id, line.approved) == (
                Decimal("8"),
                None,
                True,
            )
            assert _on(general_work, person) == []
        assert result["swept_hours"] == 0.0
        assert sorted((skip["staff_id"], skip["reason"]) for skip in result["skipped"]) == sorted(
            [(str(worker.id), "no_clock_times"), (str(other_worker.id), "no_clock_times")]
        )

    def test_G5_sick_from_one_after_working_the_morning(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, leave set-up and people
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        job: Job,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """He worked the morning on Job X and went home sick at 13:00; then the
        office booked the day's sick leave, and the day was swept.

        Leave fills the rest of the day and replaces nothing (owner, 2026-10-25).
        Guards leave_service.create_leave_request (the remainder is the day's
        leave hours less the paid hours on it) and attendance.unallocated_windows
        (the sick afternoon is not clocked time).
        """
        make_leave_job(company, superuser, "Sick Leave")
        attendance.clock_in(worker, _at(DAY, "07:00"))
        attendance.clock_out(worker, _at(DAY, "13:00"))
        # 07:00-13:00 less the 08:30 paid break and lunch: 6 - 0.25 - 0.5 = 5.25h.
        _enter(worker, worker, job, "5.25", "07:00", "13:00")

        booked = _leave(worker, LeaveType.Code.SICK, superuser)
        result = approval.sweep_person(worker, [DAY], office_staff)

        assert _on(job, worker) == [("07:00:00", "13:00:00", Decimal("5.25"), 1.0)]
        assert _on(general_work, worker) == []
        # His entry, his paid break and lunch; the 13:30 break went at clock-out.
        assert result == {"swept_hours": 0.0, "approved_count": 3, "skipped": [], "overtime": []}
        [sick] = [line for line in _day_lines(worker) if line.managed_by == "leave"]
        # 8 less the 5.25 on the job and the 0.25 paid break: 2.5h, not the
        # scenario's 2h, because he was here to 13:00 with lunch unpaid.
        assert sick.quantity == Decimal("2.5")
        assert booked["warnings"] == [_leave_warning(worker, DAY, "2h 30m")]
        assert sick.xero_pay_item is not None
        assert sick.xero_pay_item.uses_leave_api
        # 5.25 + 0.25 + 2.5: the usual day once.
        assert _paid(worker) == Decimal("8")

    def test_G6_a_day_of_sick_leave_after_a_morning_fills_the_afternoon(
        self, company: Company, superuser: Staff, job: Job, worker: Staff
    ) -> None:
        """He entered 07:00-11:00 on a job; the office books a day of sick leave.

        Guards leave_service.create_leave_request: the leave fills the rest of
        the day instead of being refused for the entry on it.
        """
        make_leave_job(company, superuser, "Sick Leave")
        _clock(worker, "07:00", "11:00")
        # 07:00-11:00 less the 08:30 paid break: 3.75h.
        _enter(worker, worker, job, "3.75", "07:00", "11:00")

        booked = _leave(worker, LeaveType.Code.SICK, superuser)

        [sick] = [line for line in _day_lines(worker) if line.managed_by == "leave"]
        # 8 less 3.75 on the job and the 0.25 paid break.
        assert sick.quantity == Decimal("4")
        assert booked["warnings"] == [_leave_warning(worker, DAY, "4h")]
        assert _paid(worker) == Decimal("8")

    def test_G7_a_whole_day_of_leave_on_an_empty_day_is_eight_hours(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """A whole day of annual leave on a day with nothing on it.

        Guards leave_service.create_leave_request: nothing to take off, so the
        whole day's hours.
        """
        make_leave_job(company, superuser, "Annual Leave")

        booked = _leave(worker, LeaveType.Code.ANNUAL, superuser)

        assert booked["warnings"] == []
        [leave_line] = _day_lines(worker)
        assert (leave_line.quantity, leave_line.managed_by) == (Decimal("8"), "leave")
        assert _paid(worker) == Decimal("8")

    def test_G8_leave_on_a_day_already_full_puts_nothing_to_leave_and_warns(
        self, company: Company, superuser: Staff, job: Job, worker: Staff
    ) -> None:
        """He entered a full 8h on a job; the office books a day of leave on it.

        Not refused (owner, 2026-10-25): 8 less 8 paid leaves 0h to put to
        leave, and the office is told.
        Guards leave_service.create_leave_request's fill and its warning.
        """
        make_leave_job(company, superuser, "Annual Leave")
        # 8h from 07:00 around the planned breaks, unclocked: 8h paid.
        _enter(worker, worker, job, "8")

        booked = _leave(worker, LeaveType.Code.ANNUAL, superuser)

        assert booked["warnings"] == [_leave_warning(worker, DAY, "0h")]
        assert _leave_hours(worker) == Decimal(0)
        assert _paid(worker) == Decimal("8")


# ── R. Sweeping, the hairy cases ───────────────────────────────────────


@pytest.mark.usefixtures("general_work")
class TestSweepingHairyCases:
    def test_R1_a_clock_out_corrected_earlier_takes_off_the_swept_time_after_it(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """Swept to 15:00, then the office corrects his clock-out to 14:00.

        Guards attendance.drop_sweep_outside_clock.
        """
        _clock(worker, "07:00", "15:00")
        approval.sweep_person(worker, [DAY], office_staff)

        _clock(worker, "07:00", "14:00", by=office_staff)
        corrected = _on(general_work, worker)
        again = approval.sweep_person(worker, [DAY], office_staff)

        # The 13:45-15:00 entry reached past 14:00 and went whole.
        assert corrected == STANDARD_GENERAL_WORK[:3]
        # The re-sweep books what is still clocked: 13:45-14:00.
        assert again == {"swept_hours": 0.25, "approved_count": 0, "skipped": [], "overtime": []}
        assert _on(general_work, worker) == [
            *STANDARD_GENERAL_WORK[:3],
            ("13:45:00", "14:00:00", Decimal("0.25"), 1.0),
        ]
        # 1.5 + 2.75 + 1.5 + 0.25 = 6 + 0.5 paid breaks.
        assert _paid(worker) == Decimal("6.5")

    def test_R2_a_clock_in_corrected_earlier_is_swept_for_the_new_hour_only(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """Swept from 07:00, then the office corrects his clock-in to 06:00.

        Guards attendance.unallocated_windows: a re-sweep books only the stretch
        not already on General work.
        """
        _clock(worker, "07:00", "15:00")
        approval.sweep_person(worker, [DAY], office_staff)
        _clock(worker, "06:00", "15:00", by=office_staff)

        again = approval.sweep_person(worker, [DAY], office_staff)

        assert again == {"swept_hours": 1.0, "approved_count": 0, "skipped": [], "overtime": []}
        # 7h already worked, so the eighth hour is still ordinary.
        assert _on(general_work, worker) == [
            ("06:00:00", "07:00:00", Decimal("1"), 1.0),
            *STANDARD_GENERAL_WORK,
        ]
        assert _paid(worker) == Decimal("8.5")

    def test_R3_untimed_entries_are_laid_out_first_and_swept_around(
        self, office_staff: Staff, job: Job, general_work: Job, worker: Staff
    ) -> None:
        """He had 3h on Job X with no times; clocked 07:00-15:00; the office sweeps.

        Guards attendance.unallocated_windows: an untimed entry takes the day from
        clock-in, around the breaks, before General work is placed.
        """
        # Legacy shape: an entry saved before the drawer placed every entry
        # carries hours and no times. Today create_entry always places one.
        legacy = make_time_line(job, worker, accounting_date=DAY, hours="3.000", approved=False)
        _clock(worker, "07:00", "15:00")

        result = approval.sweep_person(worker, [DAY], office_staff)

        # Laid 07:00 to 10:15 around the 08:30 break; General work after it.
        assert _on(general_work, worker) == [
            ("10:15:00", "11:30:00", Decimal("1.25"), 1.0),
            *STANDARD_GENERAL_WORK[2:],
        ]
        assert result == {"swept_hours": 4.0, "approved_count": 4, "skipped": [], "overtime": []}
        legacy.refresh_from_db()
        assert (legacy.quantity, legacy.approved) == (Decimal("3"), True)
        assert "start_time" not in legacy.meta
        assert _paid(worker) == Decimal("7.5")

    def test_R4_a_lunch_he_worked_through_is_swept_as_general_work(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """He deleted his lunch (worked through it), then the day is swept.

        Guards attendance.unallocated_windows reading his breaks as they stand.
        """
        _clock(worker, "07:00", "15:00")
        attendance.remove_break(_break_at(worker, time(11, 30)), worker)

        result = approval.sweep_person(worker, [DAY], office_staff)

        # 1.5 + 08:45-13:30 4.75 + 1.25 = 7.5h, lunch included.
        assert _on(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.5"), 1.0),
            ("08:45:00", "13:30:00", Decimal("4.75"), 1.0),
            ("13:45:00", "15:00:00", Decimal("1.25"), 1.0),
        ]
        assert result == {"swept_hours": 7.5, "approved_count": 2, "skipped": [], "overtime": []}
        # 7.5 + 0.5 paid breaks.
        assert _paid(worker) == Decimal("8")

    def test_R5_a_week_sweep_skips_the_weekend_when_weekends_are_off(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """The office sweeps Friday to Monday; weekend timesheets are off.

        Guards approval._people_on and approval._rostered: nobody is rostered on
        Saturday or Sunday.
        """
        friday, monday = DAY + timedelta(days=4), DAY + timedelta(days=7)

        result = approval.sweep_everyone(approval.sweep_days(friday, monday), office_staff)

        # Friday and Monday, 7h each.
        assert result == {"swept_hours": 14.0, "approved_count": 0, "skipped": [], "overtime": []}
        for weekend in (friday + timedelta(days=1), friday + timedelta(days=2)):
            assert _day_lines(worker, weekend) == []
            assert not AttendanceDay.objects.filter(staff=worker, date=weekend).exists()
        assert _on(general_work, worker, monday) == STANDARD_GENERAL_WORK

    def test_R6_leave_booked_on_a_swept_day_keeps_its_general_work_and_warns(
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """The day was swept as a standard day; then the office books a day of annual leave.

        Leave replaces nothing (owner, 2026-10-25): the swept General work stays,
        the leave fills only what is left of the day, and the office is told.
        Guards leave_service.create_leave_request on a day carrying swept General work.
        """
        make_leave_job(company, superuser, "Annual Leave")
        approval.sweep_person(worker, [DAY], office_staff)

        booked = _leave(worker, LeaveType.Code.ANNUAL, superuser)

        assert _on(general_work, worker) == STANDARD_GENERAL_WORK
        # The day's leave hours less the paid hours on it: 8 - (7 General work
        # + 0.5 paid breaks) = 0.5h to leave.
        assert _leave_hours(worker) == Decimal("0.5")
        assert booked["warnings"] == [_leave_warning(worker, DAY, "30m")]
        # 7.5 + 0.5 leave.
        assert _paid(worker) == Decimal("8")

    def test_R7_an_office_closure_over_a_swept_day_keeps_its_general_work_and_warns(  # noqa: PLR0913, PLR0917 -- pytest fixtures: the jobs, leave set-up and people
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
        other_worker: Staff,
    ) -> None:
        """Monday was swept for everyone; then the office closes Monday and Tuesday.

        As R6, for every person: Monday keeps its General work and the holiday
        fills only what is left, with a warning per person; Tuesday is a whole
        holiday.
        Guards leave_service.create_office_closure over swept days.
        """
        holiday = make_public_holiday_job(company, superuser)
        tuesday = DAY + timedelta(days=1)
        approval.sweep_everyone([DAY], office_staff)

        result = leave_service.create_office_closure(
            start_date=DAY, end_date=tuesday, note="Office closed", actor=superuser
        )

        assert result["skipped_days"] == []
        # Monday had 7.5h paid already: 8 - 7.5 = 0.5h to the holiday, warned.
        # Tuesday had nothing on it: no warning.
        assert sorted(result["warnings"]) == sorted(
            [_leave_warning(person, DAY, "30m") for person in (worker, other_worker)]
        )
        for person in (worker, other_worker):
            assert _on(general_work, person) == STANDARD_GENERAL_WORK
            holiday_hours = {
                line.accounting_date: line.quantity
                for line in CostLine.objects.filter(staff=person, cost_set__job=holiday)
            }
            assert holiday_hours == {DAY: Decimal("0.5"), tuesday: Decimal("8")}
            assert _paid(person) == Decimal("8")
            assert _paid(person, tuesday) == Decimal("8")

    def test_R8_swept_general_work_the_office_deleted_is_swept_again(
        self, office_staff: Staff, general_work: Job, worker: Staff
    ) -> None:
        """The office deleted part of the swept General work, then swept again.

        Guards attendance.unallocated_windows: a deleted stretch is unbooked, not unpaid.
        """
        _clock(worker, "07:00", "15:00")
        approval.sweep_person(worker, [DAY], office_staff)
        middle = CostLine.objects.get(
            staff=worker, cost_set__job=general_work, meta__start_time="12:00:00"
        )
        workshop_timesheet_service.delete_entry(office_staff, middle.id)

        again = approval.sweep_person(worker, [DAY], office_staff)

        assert again == {"swept_hours": 1.5, "approved_count": 0, "skipped": [], "overtime": []}
        assert _on(general_work, worker) == STANDARD_GENERAL_WORK
        assert _paid(worker) == Decimal("7.5")


# ── V. Leave and days off ──────────────────────────────────────────────


@pytest.mark.usefixtures("general_work")
class TestLeaveAndDaysOff:
    def test_V1_a_full_day_of_leave_and_a_full_day_worked_is_flagged(
        self, company: Company, superuser: Staff, job: Job, worker: Staff
    ) -> None:
        """He had 8h of annual leave booked and came in anyway, entering 8h on Job X.

        Proposed: allowed (paid 16h), and Approve time flags leave and work on the
        same day for the office.
        Guards approval._staff_day's cautions.
        """
        make_leave_job(company, superuser, "Annual Leave")
        assert _leave(worker, LeaveType.Code.ANNUAL, superuser)["warnings"] == []

        _enter(worker, worker, job, "8")

        # 8h from 07:00 around the planned breaks ends 16:00; leave is not
        # work, so all 8 are ordinary.
        assert _on(job, worker) == [("07:00:00", "16:00:00", Decimal("8"), 1.0)]
        assert _paid(worker) == Decimal("16")
        cautions = _row(worker)["clock"]["cautions"]
        assert "Leave and work on the same day" in cautions, cautions

    def test_V2_half_a_sick_day_after_a_short_clocked_morning(
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """Clocked 07:00-11:00 and swept; then the office books a day of sick leave.

        Guards attendance.unallocated_windows (nothing after his clock-out) and
        leave_service.create_leave_request's fill of the rest of the day.
        """
        make_leave_job(company, superuser, "Sick Leave")
        _clock(worker, "07:00", "11:00")
        result = approval.sweep_person(worker, [DAY], office_staff)

        booked = _leave(worker, LeaveType.Code.SICK, superuser)

        # 07:00-08:30 1.5 + 08:45-11:00 2.25 = 3.75h.
        assert _on(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.5"), 1.0),
            ("08:45:00", "11:00:00", Decimal("2.25"), 1.0),
        ]
        assert result == {"swept_hours": 3.75, "approved_count": 1, "skipped": [], "overtime": []}
        # 8 less 3.75 General work and the 0.25 paid break = 4h sick.
        assert _leave_hours(worker) == Decimal("4")
        assert booked["warnings"] == [_leave_warning(worker, DAY, "4h")]
        assert _paid(worker) == Decimal("8")

    def test_V3_leave_deleted_after_the_sweep_leaves_the_day_short(
        self,
        office_staff: Staff,
        company: Company,
        superuser: Staff,
        general_work: Job,
        worker: Staff,
    ) -> None:
        """As V2, then the sick leave is deleted and the day swept again.

        Guards attendance.unallocated_windows: the re-sweep invents nothing past his clock.
        """
        make_leave_job(company, superuser, "Sick Leave")
        _clock(worker, "07:00", "11:00")
        approval.sweep_person(worker, [DAY], office_staff)
        # 8 less 4 paid: 4h sick.
        sick = _leave(worker, LeaveType.Code.SICK, superuser)

        leave_service.delete_leave_request(UUID(sick["request"]["id"]))
        again = approval.sweep_person(worker, [DAY], office_staff)

        assert again == {"swept_hours": 0.0, "approved_count": 0, "skipped": [], "overtime": []}
        assert _on(general_work, worker) == [
            ("07:00:00", "08:30:00", Decimal("1.5"), 1.0),
            ("08:45:00", "11:00:00", Decimal("2.25"), 1.0),
        ]
        # 3.75 + 0.25: short of the standard 7.5, and left so.
        assert _paid(worker) == Decimal("4")
