# ruff: noqa: N802 -- tests are named by the plan's scenario ids (H1, K6, Q10)
"""Breaks and the entries around them: scenarios H, K, Q and W5 of the timesheet scenario list.

The company's default day: 07:00 to 15:00, with a paid break 08:30-08:45,
an unpaid lunch 11:30-12:00 and a paid break 13:30-13:45. ``set_clock_times``
puts those on a day once, when it first has a start, each one inside the
clocked span. The worker's wage is 48.00 (40.00 plus 20% loading).

The final break rules (owner, 2026-10-25):

- a person, worker or office, may add, move, resize or delete a break at any
  time; that never changes an entry and is never refused;
- the system's standard breaks go only where there is room: one is skipped
  when it falls inside an entry whose hours exceed its span less that break;
- an entry is refused only when its hours exceed its span.

Every expected figure is worked out by hand in the comment beside it.
"""

import re
from datetime import time
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.errors import InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.job_service import update_cost_line
from apps.job.services.time_entry_rates import is_unpaid_time
from apps.timesheet.models import TimesheetEvent
from apps.timesheet.services import (
    approval,
    attendance,
    day_submission,
    hour_categories,
    workshop_timesheet_service,
)
from apps.timesheet.tests.conftest import WEEK_START, make_time_line

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("break_job")]

DAY = WEEK_START

#: A line as the assertions read it: start, stop, hours and wage multiplier.
Line = tuple[str, str, Decimal, float]
#: A break as the assertions read it: start, stop, hours and whether it is paid.
Break = tuple[str, str, Decimal, bool]


@pytest.fixture
def general_work(superuser: Staff) -> Job:
    """The internal job the sweep books to, as ``create_shop_jobs`` leaves it."""
    defaults = CompanyDefaults.get_solo()
    job = make_job(defaults.shop_company, superuser, name="General work", status="special")
    defaults.general_work_job = job
    defaults.save(update_fields=["general_work_job"])
    return job


@pytest.fixture
def job_y(company: Company, superuser: Staff) -> Job:
    return make_job(company, superuser, name="Job Y")


@pytest.fixture
def job_z(company: Company, superuser: Staff) -> Job:
    return make_job(company, superuser, name="Job Z")


def _clock(worker: Staff, start: str, finish: str | None) -> None:
    """Set his clock times by hand, as My time does for a forgotten tap."""
    attendance.set_clock_times(
        worker,
        DAY,
        time.fromisoformat(start),
        None if finish is None else time.fromisoformat(finish),
        worker,
    )


def _book(worker: Staff, job: Job, start: str, end: str) -> UUID:
    """Book a job as the drawer does: the hours are the placement rule's answer."""
    hours = attendance.hours_for(
        time.fromisoformat(start),
        time.fromisoformat(end),
        workshop_timesheet_service.day_break_windows(worker, DAY),
    )
    entry = workshop_timesheet_service.create_entry(
        worker,
        worker,
        {
            "job_id": job.id,
            "accounting_date": DAY,
            "hours": hours,
            "start_time": time.fromisoformat(start),
            "end_time": time.fromisoformat(end),
            "wage_rate_multiplier": Decimal("1.0"),
        },
    )
    return UUID(entry["id"])


def _edit_times(worker: Staff, entry_id: UUID, start: str, end: str) -> None:
    """Edit an entry's times as the drawer does: the hours are the placement rule's answer."""
    hours = attendance.hours_for(
        time.fromisoformat(start),
        time.fromisoformat(end),
        workshop_timesheet_service.day_break_windows(worker, DAY),
    )
    workshop_timesheet_service.update_entry(
        worker,
        {
            "entry_id": entry_id,
            "hours": hours,
            "start_time": time.fromisoformat(start),
            "end_time": time.fromisoformat(end),
        },
    )


def _as_line(line: CostLine) -> Line:
    return (
        line.meta["start_time"],
        line.meta["end_time"],
        line.quantity,
        line.meta["wage_rate_multiplier"],
    )


def _on(job: Job, worker: Staff) -> list[Line]:
    """The job's lines for him, in the order made."""
    return [
        _as_line(line)
        for line in CostLine.objects.filter(staff=worker, cost_set__job=job).order_by("created_at")
    ]


def _entry(entry_id: UUID) -> Line:
    return _as_line(CostLine.objects.get(id=entry_id))


def _break_job_id() -> UUID:
    job_id = attendance.break_job_id()
    assert job_id is not None, "the break_job fixture sets it"
    return job_id


def _breaks(worker: Staff) -> list[Break]:
    """His break lines for the day, in the day's order."""
    lines = CostLine.objects.filter(
        staff=worker, accounting_date=DAY, cost_set__job_id=_break_job_id()
    ).select_related("xero_pay_item")
    return sorted(
        (line.meta["start_time"], line.meta["end_time"], line.quantity, not is_unpaid_time(line))
        for line in lines
    )


def _break_at(worker: Staff, start: str) -> CostLine:
    """His one break line that starts at ``start``."""
    return CostLine.objects.get(
        staff=worker,
        accounting_date=DAY,
        cost_set__job_id=_break_job_id(),
        meta__start_time=f"{start}:00",
    )


def _break_at_window(worker: Staff, start: str) -> Break:
    """His break that starts at ``start``, as the assertions read it."""
    line = _break_at(worker, start)
    return (line.meta["start_time"], line.meta["end_time"], line.quantity, not is_unpaid_time(line))


def _paid(worker: Staff) -> Decimal:
    """Hours he is paid for the day: every time line that is not unpaid time."""
    lines = workshop_timesheet_service.day_time_lines(worker, DAY)
    return sum((line.quantity for line in lines if not is_unpaid_time(line)), Decimal(0))


def _billed(worker: Staff) -> Decimal:
    """Hours billed to customers for the day: lines that bill their job."""
    lines = workshop_timesheet_service.day_time_lines(worker, DAY)
    return sum((line.quantity for line in lines if hour_categories.is_billable(line)), Decimal(0))


def _minutes(hours: Decimal) -> int:
    """Hours as whole minutes, for a figure that is not a whole number of hundredths."""
    return int((hours * 60).to_integral_value(ROUND_HALF_UP))


def _swept(general_work: Job, worker: Staff) -> list[tuple[str, str, Decimal]]:
    return sorted(
        (line.meta["start_time"], line.meta["end_time"], line.quantity)
        for line in CostLine.objects.filter(cost_set__job=general_work, staff=worker)
    )


# ── H. Breaks ───────────────────────────────────────────────────────────


def test_H1_a_break_inside_an_entry_is_not_billed_and_is_paid_as_a_break(
    worker: Staff, job: Job
) -> None:
    """Clocked in 07:00, break 07:30-08:00, job 07:00-09:00: billed and paid 1.5h on the job,
    plus the break, which is paid. The breaks are set before anything is entered.

    Guards attendance.hours_for and workshop_timesheet_service.create_entry.
    """
    # Clocked 07:00-09:00: only the 08:30-08:45 standard break fits, and he
    # took his at 07:30 instead; nothing is entered yet, so both are allowed.
    _clock(worker, "07:00", "09:00")
    attendance.remove_break(_break_at(worker, "08:30").id, worker)
    attendance.add_break(worker, DAY, time(7, 30), time(8, 0), paid=True, actor=worker)

    _book(worker, job, "07:00", "09:00")

    # 120 minutes less the 30-minute break = 90 = 1.5h.
    assert _on(job, worker) == [("07:00:00", "09:00:00", Decimal("1.500"), 1.0)]
    assert _breaks(worker) == [("07:30:00", "08:00:00", Decimal("0.500"), True)]
    assert _billed(worker) == Decimal("1.5")
    # 1.5 on the job + 0.5 paid break = 2.0.
    assert _paid(worker) == Decimal("2.0")


def test_H2_lunch_deleted_leaves_the_entry_and_he_edits_it_to_take_the_half_hour(
    worker: Staff, job: Job
) -> None:
    """He worked through lunch and deletes it: the entry is unchanged. He then edits the
    entry, and 07:00-15:00 with lunch gone holds 7.5h, billed and paid.

    Guards attendance.remove_break (changes no entry) and the hours rule on update_entry.
    """
    _clock(worker, "07:00", "15:00")
    # 480 less 15 + 30 + 15 = 420 = 7.0h.
    entry = _book(worker, job, "07:00", "15:00")

    attendance.remove_break(_break_at(worker, "11:30").id, worker)
    after_delete = _entry(entry)
    _edit_times(worker, entry, "07:00", "15:00")

    assert after_delete == ("07:00:00", "15:00:00", Decimal("7.000"), 1.0)
    # 480 less the two 15-minute paid breaks = 450 = 7.5h.
    assert _entry(entry) == ("07:00:00", "15:00:00", Decimal("7.500"), 1.0)
    assert _billed(worker) == Decimal("7.5")
    # 7.5 on the job + 0.25 + 0.25 paid breaks = 8.0.
    assert _paid(worker) == Decimal("8.0")


def test_H3_a_paid_break_shortened_inside_an_entry_changes_no_entry(
    worker: Staff, job: Job
) -> None:
    """A paid break shortened from 15 to 10 minutes inside an entry: allowed, and the
    entry keeps its hours.

    Guards attendance.change_break (changes no entry).
    """
    _clock(worker, "07:00", "15:00")
    # 120 less the 15-minute break = 105 minutes.
    entry = _book(worker, job, "08:00", "10:00")

    attendance.change_break(_break_at(worker, "08:30").id, time(8, 30), time(8, 40), worker)

    assert _entry(entry) == ("08:00:00", "10:00:00", Decimal("1.750"), 1.0)
    start, end, hours, paid = _break_at_window(worker, "08:30")
    # 10 minutes; not a whole number of hundredths, so read in minutes.
    assert (start, end, _minutes(hours), paid) == ("08:30:00", "08:40:00", 10, True)


def test_H4_a_break_added_inside_an_entry_changes_no_entry(worker: Staff, job: Job) -> None:
    """A break added inside an entry: accepted, and the entry keeps its hours (a break
    never changes an entry; the office checks the day).

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    # 09:00-10:00 holds no standard break: 1.0h.
    entry = _book(worker, job, "09:00", "10:00")

    attendance.add_break(worker, DAY, time(9, 30), time(9, 45), paid=True, actor=worker)

    assert _entry(entry) == ("09:00:00", "10:00:00", Decimal("1.000"), 1.0)
    assert _break_at_window(worker, "09:30") == ("09:30:00", "09:45:00", Decimal("0.250"), True)
    # 1.0 on the job + 0.25 (08:30) + 0.25 (09:30) + 0.25 (13:30) paid breaks = 1.75.
    assert _paid(worker) == Decimal("1.75")


def test_H5_a_break_moved_from_one_entry_into_the_next_changes_neither(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """A break moved from inside entry A to inside entry B: allowed, and both entries
    keep their hours.

    Guards attendance.change_break (changes no entry).
    """
    _clock(worker, "07:00", "15:00")
    # 120 less the 08:30 break 15 = 1.75h.
    a = _book(worker, job, "08:00", "10:00")
    # 60 minutes, nothing inside.
    b = _book(worker, job_y, "10:00", "11:00")

    attendance.change_break(_break_at(worker, "08:30").id, time(10, 15), time(10, 30), worker)

    assert _entry(a) == ("08:00:00", "10:00:00", Decimal("1.750"), 1.0)
    assert _entry(b) == ("10:00:00", "11:00:00", Decimal("1.000"), 1.0)
    assert _breaks(worker) == [
        ("10:15:00", "10:30:00", Decimal("0.250"), True),
        ("11:30:00", "12:00:00", Decimal("0.500"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]


def test_H6_a_break_moved_across_two_entries_changes_neither(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """A break moved and stretched to straddle the end of one entry and the start of the
    next: allowed, and each entry keeps its hours.

    Guards attendance.change_break (changes no entry).
    """
    _clock(worker, "07:00", "15:00")
    a = _book(worker, job, "09:00", "10:00")
    b = _book(worker, job_y, "10:00", "11:00")

    attendance.change_break(_break_at(worker, "08:30").id, time(9, 45), time(10, 15), worker)

    # Each keeps its 60 minutes.
    assert _entry(a) == ("09:00:00", "10:00:00", Decimal("1.000"), 1.0)
    assert _entry(b) == ("10:00:00", "11:00:00", Decimal("1.000"), 1.0)
    # 30 minutes, still paid.
    assert _break_at_window(worker, "09:45") == ("09:45:00", "10:15:00", Decimal("0.500"), True)


def test_H7_a_break_over_a_whole_quarter_hour_entry_changes_no_entry(
    worker: Staff, job: Job
) -> None:
    """A break added over a whole 15-minute entry: accepted, and the entry keeps its
    quarter hour for the office to judge.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    entry = _book(worker, job, "10:00", "10:15")

    attendance.add_break(worker, DAY, time(10, 0), time(10, 15), paid=True, actor=worker)

    assert _entry(entry) == ("10:00:00", "10:15:00", Decimal("0.250"), 1.0)
    assert _break_at_window(worker, "10:00") == ("10:00:00", "10:15:00", Decimal("0.250"), True)
    # 0.25 on the job + 0.25 (08:30) + 0.25 (10:00) + 0.25 (13:30) paid breaks = 1.0.
    assert _paid(worker) == Decimal("1.0")


def test_H8_a_longer_lunch_is_unpaid_and_a_longer_paid_break_is_paid(worker: Staff) -> None:
    """A longer lunch is unpaid for its full length; a longer paid break is paid.

    Guards attendance.change_break (it keeps the break's kind).
    """
    _clock(worker, "07:00", "15:00")

    attendance.change_break(_break_at(worker, "08:30").id, time(8, 30), time(9, 0), worker)
    attendance.change_break(_break_at(worker, "11:30").id, time(11, 30), time(12, 15), worker)

    assert _breaks(worker) == [
        ("08:30:00", "09:00:00", Decimal("0.500"), True),
        ("11:30:00", "12:15:00", Decimal("0.750"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]
    # 0.5 + 0.25 paid breaks; the 0.75 lunch is not paid = 0.75.
    assert _paid(worker) == Decimal("0.75")


def test_H9_a_break_outside_his_clock_times_is_not_made_but_one_he_adds_stands(
    worker: Staff,
) -> None:
    """A break outside his clock times is not generated; if he adds one (nothing entered
    yet) it is accepted and the office sees it.

    Guards attendance.generate_default_breaks and attendance.add_break.
    """
    # Clocked 09:00-12:00: the 08:30 break is before his start and the 13:30
    # one after his finish; only lunch fits.
    _clock(worker, "09:00", "12:00")
    generated = _breaks(worker)

    attendance.add_break(worker, DAY, time(13, 30), time(13, 45), paid=True, actor=worker)

    assert generated == [("11:30:00", "12:00:00", Decimal("0.500"), False)]
    office_view = workshop_timesheet_service.list_entries(worker, DAY)["breaks"]
    assert [(each["start"], each["end"], each["paid"]) for each in office_view] == [
        (time(11, 30), time(12, 0), False),
        (time(13, 30), time(13, 45), True),
    ]


def test_H10_the_office_moving_a_break_in_the_grid_changes_no_entry(
    office_staff: Staff, worker: Staff, job: Job
) -> None:
    """The office moves a break from the entry grid: allowed, as from his phone, and the
    entry keeps its hours.

    Guards job_service.update_cost_line (the grid's write changes no other line).
    """
    _clock(worker, "07:00", "15:00")
    # 120 less the 08:30 break 15 = 1.75h.
    entry = _book(worker, job, "08:00", "10:00")
    morning = _break_at(worker, "08:30")

    update_cost_line(
        morning,
        {
            "quantity": Decimal("0.250"),
            "meta": {**morning.meta, "start_time": "10:30:00", "end_time": "10:45:00"},
        },
        office_staff,
    )

    assert _entry(entry) == ("08:00:00", "10:00:00", Decimal("1.750"), 1.0)
    assert _break_at_window(worker, "10:30") == ("10:30:00", "10:45:00", Decimal("0.250"), True)


def test_H11_breaks_are_added_and_moved_freely_before_anything_is_entered(
    worker: Staff,
) -> None:
    """On a day with no time entered, adding a break and moving one both work.

    Guards attendance.add_break and attendance.change_break.
    """
    _clock(worker, "07:00", "15:00")

    attendance.add_break(worker, DAY, time(10, 0), time(10, 15), paid=True, actor=worker)
    attendance.change_break(_break_at(worker, "08:30").id, time(9, 0), time(9, 15), worker)

    assert _breaks(worker) == [
        ("09:00:00", "09:15:00", Decimal("0.250"), True),
        ("10:00:00", "10:15:00", Decimal("0.250"), True),
        ("11:30:00", "12:00:00", Decimal("0.500"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]


# ── K. Several entries in a day, around and through breaks ─────────────


def test_K1_three_jobs_across_the_standard_day_bill_seven_hours_and_pay_seven_and_a_half(
    worker: Staff, job: Job, job_y: Job, job_z: Job
) -> None:
    """X 07:00-10:00, Y 10:00-13:00, Z 13:00-15:00: X 2.75h, Y 2.5h, Z 1.75h;
    7h billed across three jobs, 7.5h paid.

    Guards attendance.hours_for and workshop_timesheet_service.create_entry.
    """
    _clock(worker, "07:00", "15:00")

    _book(worker, job, "07:00", "10:00")
    _book(worker, job_y, "10:00", "13:00")
    _book(worker, job_z, "13:00", "15:00")

    # 180 less the 08:30 break (15) = 165 minutes.
    assert _on(job, worker) == [("07:00:00", "10:00:00", Decimal("2.750"), 1.0)]
    # 180 less lunch (30) = 150 minutes.
    assert _on(job_y, worker) == [("10:00:00", "13:00:00", Decimal("2.500"), 1.0)]
    # 120 less the 13:30 break (15) = 105 minutes.
    assert _on(job_z, worker) == [("13:00:00", "15:00:00", Decimal("1.750"), 1.0)]
    # 2.75 + 2.5 + 1.75 = 7.0.
    assert _billed(worker) == Decimal("7.0")
    # 7.0 + 0.25 + 0.25 paid breaks = 7.5.
    assert _paid(worker) == Decimal("7.5")


def test_K2_entries_meeting_a_break_at_its_edges_hold_none_of_it(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """X ends as a break starts (07:00-08:30), Y starts as it ends (08:45-10:00):
    X 1.5h, Y 1.25h, the break in neither.

    Guards attendance.hours_for (a break touching an edge is not inside).
    """
    _clock(worker, "07:00", "15:00")

    _book(worker, job, "07:00", "08:30")
    _book(worker, job_y, "08:45", "10:00")

    # 90 minutes, nothing inside.
    assert _on(job, worker) == [("07:00:00", "08:30:00", Decimal("1.500"), 1.0)]
    # 75 minutes, nothing inside.
    assert _on(job_y, worker) == [("08:45:00", "10:00:00", Decimal("1.250"), 1.0)]
    assert _break_at(worker, "08:30").quantity == Decimal("0.250")


def test_K3_an_entry_starting_inside_a_break_does_not_hold_the_break_minutes(
    worker: Staff, job: Job
) -> None:
    """An entry that starts inside a break (08:40-10:00): 1.25h.

    Guards attendance.hours_for.
    """
    _clock(worker, "07:00", "15:00")

    _book(worker, job, "08:40", "10:00")

    # 80 minutes less the 5 of the break (08:40-08:45) = 75 = 1.25h.
    assert _on(job, worker) == [("08:40:00", "10:00:00", Decimal("1.250"), 1.0)]


def test_K4_an_entry_ending_inside_a_break_does_not_hold_the_break_minutes(
    worker: Staff, job: Job
) -> None:
    """An entry that ends inside a break (07:00-08:40): 1.5h.

    Guards attendance.hours_for.
    """
    _clock(worker, "07:00", "15:00")

    _book(worker, job, "07:00", "08:40")

    # 100 minutes less the 10 of the break (08:30-08:40) = 90 = 1.5h.
    assert _on(job, worker) == [("07:00:00", "08:40:00", Decimal("1.500"), 1.0)]


def test_K5_an_entry_wholly_inside_lunch_is_refused_with_the_reason(
    worker: Staff, job: Job
) -> None:
    """An entry wholly inside lunch (11:35-11:55) is refused, with the reason given:
    "That is all inside your lunch. If you worked through it, delete the lunch."

    Guards attendance.hours_for and workshop_timesheet_service.create_entry
    (wherever the refusal lands, the drawer's path goes through both).
    """
    _clock(worker, "07:00", "15:00")

    with pytest.raises(
        InvalidInputError,
        match=re.escape(
            "That is all inside your lunch. If you worked through it, delete the lunch."
        ),
    ):
        _book(worker, job, "11:35", "11:55")

    assert _on(job, worker) == []


def test_K6_lunch_left_in_then_deleted_and_the_entry_edited_takes_the_half_hour(
    worker: Staff, job: Job
) -> None:
    """He worked through lunch on X (11:00-12:30) but left the lunch in: X 1h, lunch unpaid.
    Deleting the lunch leaves X at 1h; he edits X, and it holds 1.5h, billed and paid.

    Guards attendance.remove_break (changes no entry) and the hours rule on update_entry.
    """
    _clock(worker, "07:00", "15:00")
    # 90 less the 30-minute lunch = 60 minutes.
    x = _book(worker, job, "11:00", "12:30")
    with_lunch = _entry(x)
    paid_with_lunch = _paid(worker)

    attendance.remove_break(_break_at(worker, "11:30").id, worker)
    after_delete = _entry(x)
    _edit_times(worker, x, "11:00", "12:30")

    assert with_lunch == ("11:00:00", "12:30:00", Decimal("1.000"), 1.0)
    # 1.0 + 0.25 + 0.25 paid breaks; lunch unpaid = 1.5.
    assert paid_with_lunch == Decimal("1.5")
    assert after_delete == ("11:00:00", "12:30:00", Decimal("1.000"), 1.0)
    # 90 minutes, nothing inside.
    assert _entry(x) == ("11:00:00", "12:30:00", Decimal("1.500"), 1.0)
    assert _billed(worker) == Decimal("1.5")
    # 1.5 + 0.25 + 0.25 = 2.0.
    assert _paid(worker) == Decimal("2.0")


def test_K7_a_paid_break_worked_through_and_left_in_bills_less_and_pays_the_hour(
    worker: Staff, job: Job
) -> None:
    """He worked through a paid break (X 08:00-09:00) and left it in:
    X billed 0.75h, paid 0.75h plus the 0.25h break: 1h paid.

    Guards attendance.hours_for and the Break job's paid line.
    """
    # Clocked 08:00-09:00: only the 08:30 break fits.
    _clock(worker, "08:00", "09:00")

    _book(worker, job, "08:00", "09:00")

    # 60 less 15 = 45 minutes.
    assert _on(job, worker) == [("08:00:00", "09:00:00", Decimal("0.750"), 1.0)]
    assert _breaks(worker) == [("08:30:00", "08:45:00", Decimal("0.250"), True)]
    assert _billed(worker) == Decimal("0.75")
    # 0.75 + 0.25 = 1.0.
    assert _paid(worker) == Decimal("1.0")


def test_K8_a_deleted_paid_break_leaves_the_entry_until_he_edits_it_to_the_hour(
    worker: Staff, job: Job
) -> None:
    """He deletes that paid break: X stays 0.75h, so he is paid 0.75h until he edits X.
    Edited, X is billed 1h and paid 1h: pay is back to 1h and the bill up 0.25h.

    Guards attendance.remove_break (changes no entry) and the hours rule on update_entry.
    """
    _clock(worker, "08:00", "09:00")
    x = _book(worker, job, "08:00", "09:00")

    attendance.remove_break(_break_at(worker, "08:30").id, worker)
    after_delete, paid_after_delete = _entry(x), _paid(worker)
    _edit_times(worker, x, "08:00", "09:00")

    assert after_delete == ("08:00:00", "09:00:00", Decimal("0.750"), 1.0)
    # The 0.25 break is gone and X is still 0.75.
    assert paid_after_delete == Decimal("0.75")
    # 60 minutes, nothing inside.
    assert _entry(x) == ("08:00:00", "09:00:00", Decimal("1.000"), 1.0)
    assert _breaks(worker) == []
    assert _billed(worker) == Decimal("1.0")
    assert _paid(worker) == Decimal("1.0")


def test_K9_lunch_deleted_and_the_entry_edited_past_eight_hours_stays_ordinary(
    worker: Staff, job: Job
) -> None:
    """Deleting the lunch on an 8h day leaves the entry at 8h; editing it to take the half
    hour puts his job time past 8h, and an edit never re-rates: the extra stays ordinary.

    (The Approve-time flag the scenario also proposes has no surface yet and is
    not asserted here.)

    Guards attendance.remove_break (changes no entry) and update_entry (no re-rating).
    """
    _clock(worker, "07:00", "16:00")
    # 540 minutes less 15 + 30 + 15 = 480 = 8.0h: exactly the usual day, no overtime.
    x = _book(worker, job, "07:00", "16:00")

    attendance.remove_break(_break_at(worker, "11:30").id, worker)
    after_delete = _entry(x)
    _edit_times(worker, x, "07:00", "16:00")

    assert after_delete == ("07:00:00", "16:00:00", Decimal("8.000"), 1.0)
    # 540 less 15 + 15 = 510 = 8.5h, still one ordinary line.
    assert _on(job, worker) == [("07:00:00", "16:00:00", Decimal("8.500"), 1.0)]
    # 8.5 + 0.25 + 0.25 = 9.0.
    assert _paid(worker) == Decimal("9.0")


def test_K10_one_entry_across_the_standard_day_holds_all_three_breaks(
    worker: Staff, job: Job
) -> None:
    """One entry 07:00-15:00 holding all three breaks: 7h.

    Guards attendance.hours_for.
    """
    _clock(worker, "07:00", "15:00")

    _book(worker, job, "07:00", "15:00")

    # 480 less 15 + 30 + 15 = 420 = 7.0h.
    assert _on(job, worker) == [("07:00:00", "15:00:00", Decimal("7.000"), 1.0)]
    assert _billed(worker) == Decimal("7.0")
    # 7.0 + 0.25 + 0.25 = 7.5.
    assert _paid(worker) == Decimal("7.5")


def test_K11_a_gap_between_entries_is_swept_to_general_work(
    office_staff: Staff, worker: Staff, job: Job, job_y: Job, general_work: Job
) -> None:
    """A gap between entries (X 07:00-09:00, Y 10:00-12:00): the sweep books 09:00-10:00
    as General work.

    Guards attendance.unallocated_windows and approval.sweep_person.
    """
    # Clocked 07:00-12:00: the 08:30 break and lunch fit.
    _clock(worker, "07:00", "12:00")
    _book(worker, job, "07:00", "09:00")
    _book(worker, job_y, "10:00", "12:00")

    approval.sweep_person(worker, [DAY], office_staff)

    assert _swept(general_work, worker) == [("09:00:00", "10:00:00", Decimal("1.000"))]
    # X 120-15 = 1.75, Y 120-30 = 1.5, General work 1.0, 08:30 break 0.25 = 4.5.
    assert _paid(worker) == Decimal("4.5")
    # General work bills nobody: 1.75 + 1.5 = 3.25.
    assert _billed(worker) == Decimal("3.25")


def test_K12_a_gap_that_is_exactly_a_break_has_nothing_to_sweep(
    office_staff: Staff, worker: Staff, job: Job, job_y: Job, general_work: Job
) -> None:
    """A gap between entries that is exactly a break: nothing to sweep.

    Guards attendance.unallocated_windows.
    """
    _clock(worker, "07:00", "12:00")
    _book(worker, job, "07:00", "08:30")
    _book(worker, job_y, "08:45", "12:00")

    result = approval.sweep_person(worker, [DAY], office_staff)

    assert _swept(general_work, worker) == []
    assert result["swept_hours"] == 0


def test_K13_two_overlapping_entries_across_a_break_each_lose_it_and_both_pay(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """Two overlapping entries both spanning the 08:30 break: each loses its 15 minutes.
    Both are billed, both paid.

    (The overlap warning is the drawer's, on the screen; nothing server-side is
    asserted for it.)

    Guards attendance.hours_for and workshop_timesheet_service.create_entry.
    """
    # Clocked 08:00-10:00: only the 08:30 break fits.
    _clock(worker, "08:00", "10:00")

    _book(worker, job, "08:00", "10:00")
    _book(worker, job_y, "08:00", "10:00")

    # 120 less 15 = 105 minutes each.
    assert _on(job, worker) == [("08:00:00", "10:00:00", Decimal("1.750"), 1.0)]
    assert _on(job_y, worker) == [("08:00:00", "10:00:00", Decimal("1.750"), 1.0)]
    assert _billed(worker) == Decimal("3.5")
    # 1.75 + 1.75 + 0.25 break = 3.75.
    assert _paid(worker) == Decimal("3.75")


def test_K14_a_break_added_over_lunch_changes_no_entry(worker: Staff, job: Job) -> None:
    """He adds a break overlapping lunch (11:45-12:15) with an entry spanning both:
    accepted, and the entry keeps its hours.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    # 120 less lunch 30 = 90 minutes.
    x = _book(worker, job, "11:00", "13:00")

    attendance.add_break(worker, DAY, time(11, 45), time(12, 15), paid=False, actor=worker)

    assert _entry(x) == ("11:00:00", "13:00:00", Decimal("1.500"), 1.0)
    # 30 minutes, unpaid.
    assert _break_at_window(worker, "11:45") == ("11:45:00", "12:15:00", Decimal("0.500"), False)
    # 1.5 + 0.25 + 0.25 paid breaks; lunch and the new break unpaid = 2.0.
    assert _paid(worker) == Decimal("2.0")


def test_K15_a_break_added_over_the_start_of_an_entry_changes_no_entry(
    worker: Staff, job: Job
) -> None:
    """A break added over the start of an entry (entry 09:00-10:00, break 08:50-09:10):
    accepted, and the entry keeps its hour.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "09:00", "10:00")

    attendance.add_break(worker, DAY, time(8, 50), time(9, 10), paid=True, actor=worker)

    assert _entry(x) == ("09:00:00", "10:00:00", Decimal("1.000"), 1.0)
    start, end, hours, paid = _break_at_window(worker, "08:50")
    # 20 minutes; not a whole number of hundredths, so read in minutes.
    assert (start, end, _minutes(hours), paid) == ("08:50:00", "09:10:00", 20, True)


def test_K16_an_entry_stretched_back_across_a_break_has_the_span_less_the_break(
    worker: Staff, job: Job
) -> None:
    """He edits an entry's times across a break (09:00-10:00 to 08:00-10:00):
    the hours follow the new span less the break, 1.75h. Not re-rated.

    Guards workshop_timesheet_service.update_entry with the drawer's placement hours.
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "09:00", "10:00")

    _edit_times(worker, x, "08:00", "10:00")

    # 120 less the 08:30 break 15 = 105 minutes.
    assert _entry(x) == ("08:00:00", "10:00:00", Decimal("1.750"), 1.0)


def test_K17_an_entry_whose_stop_is_moved_has_the_new_span_less_its_breaks(
    worker: Staff, job: Job
) -> None:
    """He edits only the stop: the hours are the new span less the breaks inside it.

    Guards workshop_timesheet_service.update_entry with the drawer's placement hours.
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "09:00", "10:00")

    _edit_times(worker, x, "09:00", "12:00")

    # 180 less lunch 30 = 150 minutes = 2.5h.
    assert _entry(x) == ("09:00:00", "12:00:00", Decimal("2.500"), 1.0)


def test_K18_the_fill_sheet_lays_three_rows_round_the_breaks_to_the_finish(  # noqa: PLR0913, PLR0917 -- pytest fixtures: three jobs, the sweep's job and two people
    office_staff: Staff, worker: Staff, job: Job, job_y: Job, job_z: Job, general_work: Job
) -> None:
    """The fill-day sheet: 3h, 3h, 1h with no times, from 07:00. Laid end to end around the
    breaks, finishing at 15:00. 7h, nothing left to sweep.

    Guards day_submission.lay_out_rows and day_submission.submit_day.
    """
    _clock(worker, "07:00", "15:00")
    rows: list[day_submission.FillRow] = [
        {"job_id": each.id, "hours": Decimal(hours), "description": None, "time_and_a_half": False}
        for each, hours in ((job, "3"), (job_y, "3"), (job_z, "1"))
    ]

    day_submission.submit_day(worker, DAY, rows, None, timezone.now())
    approval.sweep_person(worker, [DAY], office_staff)

    # X: 07:00-08:30 (1.5) + 08:45-10:15 (1.5) = 3h.
    assert _on(job, worker) == [("07:00:00", "10:15:00", Decimal("3.000"), 1.0)]
    # Y: 10:15-11:30 (1.25) + 12:00-13:30 (1.5) + 13:45-14:00 (0.25) = 3h.
    assert _on(job_y, worker) == [("10:15:00", "14:00:00", Decimal("3.000"), 1.0)]
    # Z: 14:00-15:00 = 1h.
    assert _on(job_z, worker) == [("14:00:00", "15:00:00", Decimal("1.000"), 1.0)]
    assert _swept(general_work, worker) == []
    # 3 + 3 + 1 = 7.0 billed; + 0.25 + 0.25 paid breaks = 7.5 paid.
    assert _billed(worker) == Decimal("7.0")
    assert _paid(worker) == Decimal("7.5")


def test_K19_an_entry_without_times_whose_turn_starts_in_a_break_begins_after_it(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """An entry without times whose turn starts inside a break begins when the break ends.

    Guards workshop_timesheet_service._placed and attendance.start_after_breaks.
    """
    _clock(worker, "07:00", "15:00")
    # Ends at 08:40, inside the 08:30-08:45 break.
    _book(worker, job, "07:00", "08:40")

    workshop_timesheet_service.create_entry(
        worker,
        worker,
        {
            "job_id": job_y.id,
            "accounting_date": DAY,
            "hours": Decimal("1"),
            "wage_rate_multiplier": Decimal("1.0"),
        },
    )

    # His turn is 08:40, inside the break: it starts at 08:45, 1h on is 09:45.
    assert _on(job_y, worker) == [("08:45:00", "09:45:00", Decimal("1.000"), 1.0)]


def test_K20_lunch_moved_within_one_long_entry_leaves_its_hours_alone(
    worker: Staff, job: Job
) -> None:
    """Lunch moved from 11:30 to 12:30, still inside the same long entry: allowed, and the
    entry's hours are unchanged.

    Guards attendance.change_break (changes no entry).
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "07:00", "15:00")

    attendance.change_break(_break_at(worker, "11:30").id, time(12, 30), time(13, 0), worker)

    # 480 less 15 + 30 + 15 = 420 = 7.0h.
    assert _entry(x) == ("07:00:00", "15:00:00", Decimal("7.000"), 1.0)
    assert _break_at_window(worker, "12:30") == ("12:30:00", "13:00:00", Decimal("0.500"), False)


def test_K21_lunch_moved_out_of_an_entry_into_a_gap_changes_no_entry(
    worker: Staff, job: Job, job_y: Job
) -> None:
    """Lunch moved out of entry A into a gap: allowed, and no entry changes. A keeps its
    1h until he edits it.

    Guards attendance.change_break (changes no entry).
    """
    _clock(worker, "07:00", "15:00")
    # 90 less lunch 30 = 1.0h.
    a = _book(worker, job, "11:00", "12:30")
    # 120 less the 13:30 break 15 = 1.75h.
    b = _book(worker, job_y, "13:00", "15:00")

    attendance.change_break(_break_at(worker, "11:30").id, time(12, 30), time(13, 0), worker)

    assert _entry(a) == ("11:00:00", "12:30:00", Decimal("1.000"), 1.0)
    assert _entry(b) == ("13:00:00", "15:00:00", Decimal("1.750"), 1.0)


def test_K22_a_break_deleted_where_no_entry_covers_it_changes_no_entry_and_is_swept(
    office_staff: Staff, worker: Staff, job: Job, job_y: Job, general_work: Job
) -> None:
    """A break deleted where no entry covers it: no entry changes. The sweep books that
    time as General work.

    Guards attendance.remove_break and attendance.unallocated_windows.
    """
    _clock(worker, "07:00", "12:00")
    a = _book(worker, job, "07:00", "08:30")
    b = _book(worker, job_y, "08:45", "11:30")

    attendance.remove_break(_break_at(worker, "11:30").id, worker)
    approval.sweep_person(worker, [DAY], office_staff)

    # 90 minutes and 165 minutes, as booked.
    assert _entry(a) == ("07:00:00", "08:30:00", Decimal("1.500"), 1.0)
    assert _entry(b) == ("08:45:00", "11:30:00", Decimal("2.750"), 1.0)
    assert _swept(general_work, worker) == [("11:30:00", "12:00:00", Decimal("0.500"))]


def test_K23_one_long_job_is_eight_ordinary_hours_holding_the_breaks_then_overtime(
    worker: Staff, job: Job
) -> None:
    """One job 07:00-17:00: the 8h ordinary line 07:00-16:00 holds all three breaks,
    and the 1.5x line is 16:00-17:00.

    Guards workshop_timesheet_service._split_at_overtime.
    """
    _clock(worker, "07:00", "17:00")

    # 600 less 15 + 30 + 15 = 540 = 9h; the usual Monday is 07:00-15:00 = 8h.
    _book(worker, job, "07:00", "17:00")

    # 8h from 07:00 stepping over 60 minutes of breaks ends at 16:00.
    assert _on(job, worker) == [
        ("07:00:00", "16:00:00", Decimal("8.000"), 1.0),
        ("16:00:00", "17:00:00", Decimal("1.000"), 1.5),
    ]
    ordinary, late = CostLine.objects.filter(staff=worker, cost_set__job=job).order_by("created_at")
    # 48.00 wage; 72.00 at time and a half.
    assert (ordinary.unit_cost, late.unit_cost) == (Decimal("48.00"), Decimal("72.00"))
    # 8 + 1 + 0.25 + 0.25 = 9.5.
    assert _paid(worker) == Decimal("9.5")


def test_K24_a_break_added_inside_the_overtime_line_changes_neither_line(
    worker: Staff, job: Job
) -> None:
    """A break added inside the 1.5x line: accepted, and both lines stand as split.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "17:00")
    _book(worker, job, "07:00", "17:00")

    attendance.add_break(worker, DAY, time(16, 15), time(16, 30), paid=False, actor=worker)

    # 9h: 8h ordinary to 16:00 over the three breaks, then 1h at 1.5x.
    assert _on(job, worker) == [
        ("07:00:00", "16:00:00", Decimal("8.000"), 1.0),
        ("16:00:00", "17:00:00", Decimal("1.000"), 1.5),
    ]
    assert _break_at_window(worker, "16:15") == ("16:15:00", "16:30:00", Decimal("0.250"), False)


def test_K25_a_break_added_inside_the_ordinary_line_changes_neither_line(
    worker: Staff, job: Job
) -> None:
    """A break added inside the ordinary line of a split day: accepted, and both lines stand.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "17:00")
    _book(worker, job, "07:00", "17:00")

    attendance.add_break(worker, DAY, time(10, 0), time(10, 15), paid=True, actor=worker)

    assert _on(job, worker) == [
        ("07:00:00", "16:00:00", Decimal("8.000"), 1.0),
        ("16:00:00", "17:00:00", Decimal("1.000"), 1.5),
    ]
    assert _break_at_window(worker, "10:00") == ("10:00:00", "10:15:00", Decimal("0.250"), True)


# ── Q. Breaks, the hairy cases ──────────────────────────────────────────


def test_Q1_a_break_added_inside_an_old_short_entry_leaves_its_hours(
    worker: Staff, job: Job
) -> None:
    """An old entry whose hours were already less than its span less its breaks
    (07:00-15:00 holding 4h). He adds a break inside it: accepted, and the 4h stand.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    # Legacy data: before the hours rule, the app saved an entry's hours as
    # typed, at most its span, so a 07:00-15:00 entry of 4h could be written.
    old = make_time_line(
        job,
        worker,
        accounting_date=DAY,
        hours="4.000",
        approved=False,
        start_time="07:00:00",
        end_time="15:00:00",
    )

    attendance.add_break(worker, DAY, time(10, 0), time(10, 15), paid=True, actor=worker)

    assert _entry(old.id) == ("07:00:00", "15:00:00", Decimal("4.000"), 1.0)
    assert _break_at_window(worker, "10:00") == ("10:00:00", "10:15:00", Decimal("0.250"), True)


def test_Q2_a_break_added_over_an_old_tiny_entry_leaves_its_hours(worker: Staff, job: Job) -> None:
    """An old 0.1h entry under a 15-minute break being added: accepted, and the entry
    keeps its 0.1h (it never goes below nothing, because a break changes no entry).

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    # Legacy data: an entry saved before the hours rule, 0.1h inside 10:00-10:15.
    old = make_time_line(
        job,
        worker,
        accounting_date=DAY,
        hours="0.100",
        approved=False,
        start_time="10:00:00",
        end_time="10:15:00",
    )

    attendance.add_break(worker, DAY, time(10, 0), time(10, 15), paid=True, actor=worker)

    assert _entry(old.id) == ("10:00:00", "10:15:00", Decimal("0.100"), 1.0)
    assert _break_at_window(worker, "10:00") == ("10:00:00", "10:15:00", Decimal("0.250"), True)


def test_Q3_an_earlier_clock_in_after_the_breaks_were_made_adds_no_break(
    worker: Staff,
) -> None:
    """His clock-in moves from 09:00 to 07:00 after the breaks were generated:
    the 08:30 break isn't added (a known accepted cost).

    Guards attendance.generate_default_breaks (once per day).
    """
    # From 09:00, the 08:30 break is before his start; lunch and 13:30 fit.
    _clock(worker, "09:00", "15:00")

    _clock(worker, "07:00", "15:00")

    assert _breaks(worker) == [
        ("11:30:00", "12:00:00", Decimal("0.500"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]


def test_Q4_an_untouched_lunch_dropped_at_clock_out_changes_no_entry(
    worker: Staff, job: Job
) -> None:
    """He clocks out at 11:00, so the untouched lunch is dropped, but an entry runs
    10:00-12:30: dropping a break changes no entry, so it keeps its 2h.

    (That the office sees an entry past his clock-out is not asserted: there is
    no flag for it yet.)

    Guards attendance.drop_breaks_after_finish (a deletion: changes no entry).
    """
    # Clocked in with no finish: all three standard breaks are put on the day.
    _clock(worker, "07:00", None)
    # 150 less lunch 30 = 2.0h.
    x = _book(worker, job, "10:00", "12:30")

    # His finish, set by hand (the forgotten tap on an earlier day).
    _clock(worker, "07:00", "11:00")

    # Lunch (ends 12:00) and 13:30 (ends 13:45) are after 11:00 and untouched: gone.
    assert _breaks(worker) == [("08:30:00", "08:45:00", Decimal("0.250"), True)]
    assert _entry(x) == ("10:00:00", "12:30:00", Decimal("2.000"), 1.0)


def test_Q5_a_double_tapped_break_changes_no_entry(worker: Staff, job: Job) -> None:
    """A double tap adds the same 15-minute break twice: both adds are a person's and are
    accepted, and the entry under them keeps its hours. The office sees both breaks.

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "09:00", "10:00")

    attendance.add_break(worker, DAY, time(9, 30), time(9, 45), paid=True, actor=worker)
    attendance.add_break(worker, DAY, time(9, 30), time(9, 45), paid=True, actor=worker)

    assert _entry(x) == ("09:00:00", "10:00:00", Decimal("1.000"), 1.0)
    assert _breaks(worker) == [
        ("08:30:00", "08:45:00", Decimal("0.250"), True),
        ("09:30:00", "09:45:00", Decimal("0.250"), True),
        ("09:30:00", "09:45:00", Decimal("0.250"), True),
        ("11:30:00", "12:00:00", Decimal("0.500"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]


def test_Q6_the_office_adding_a_break_in_an_approved_entry_changes_no_entry(
    office_staff: Staff, worker: Staff, job: Job
) -> None:
    """The office adds a break inside an approved entry: accepted, and the entry
    stays approved and unedited. The break is the office's and waits for
    approval, as anything entered does (owner, 2026-10-26).

    Guards attendance.add_break (records the break, touches no entry).
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "09:00", "10:00")
    approval.approve_day(worker, DAY, office_staff)

    attendance.add_break(worker, DAY, time(9, 30), time(9, 45), paid=True, actor=office_staff)

    assert _entry(x) == ("09:00:00", "10:00:00", Decimal("1.000"), 1.0)
    assert CostLine.objects.get(id=x).approved is True
    assert not TimesheetEvent.objects.filter(cost_line_id=x, event_type="entry_updated").exists()
    added = _break_at(worker, "09:30")
    assert added.approved is False
    [created] = TimesheetEvent.objects.filter(cost_line_id=added.id, event_type="entry_created")
    assert created.staff_id == office_staff.id


def test_Q7_a_worker_adding_a_break_on_his_approved_day_changes_no_entry(
    office_staff: Staff, worker: Staff, job: Job
) -> None:
    """He adds a break inside his approved entry: accepted, and since it changes no entry
    nothing approved moves. The break waits for the office like the rest of his time.

    Guards attendance.add_break (records the break, touches no approved entry).
    """
    _clock(worker, "07:00", "15:00")
    x = _book(worker, job, "09:00", "10:00")
    approval.approve_day(worker, DAY, office_staff)

    attendance.add_break(worker, DAY, time(9, 30), time(9, 45), paid=True, actor=worker)

    assert _entry(x) == ("09:00:00", "10:00:00", Decimal("1.000"), 1.0)
    assert CostLine.objects.get(id=x).approved is True
    assert _break_at(worker, "09:30").approved is False


def test_Q8_a_break_of_no_length_or_ending_before_it_starts_is_refused(worker: Staff) -> None:
    """A break of zero length, or with its end before its start: refused.

    Guards attendance._require_break_times.
    """
    _clock(worker, "07:00", "15:00")
    breaks_before = _breaks(worker)

    with pytest.raises(InvalidInputError, match=re.escape("A break finishes after it starts.")):
        attendance.add_break(worker, DAY, time(10, 0), time(10, 0), paid=True, actor=worker)
    with pytest.raises(InvalidInputError, match=re.escape("A break finishes after it starts.")):
        attendance.add_break(worker, DAY, time(10, 0), time(9, 45), paid=True, actor=worker)
    with pytest.raises(InvalidInputError, match=re.escape("A break finishes after it starts.")):
        attendance.change_break(_break_at(worker, "08:30").id, time(8, 45), time(8, 30), worker)

    assert _breaks(worker) == breaks_before


def test_Q9_a_break_before_his_clock_in_is_accepted_and_the_sweep_is_unaffected(
    office_staff: Staff, worker: Staff, general_work: Job
) -> None:
    """A break added before his clock-in (06:00-06:15, clocked in at 07:00), with nothing
    entered yet: accepted, and the sweep books his clocked day as it would without it.

    Guards attendance.add_break and attendance.unallocated_windows.
    """
    # Clocked 07:00-09:00: only the 08:30 break fits.
    _clock(worker, "07:00", "09:00")

    attendance.add_break(worker, DAY, time(6, 0), time(6, 15), paid=True, actor=worker)
    approval.sweep_person(worker, [DAY], office_staff)

    assert _breaks(worker) == [
        ("06:00:00", "06:15:00", Decimal("0.250"), True),
        ("08:30:00", "08:45:00", Decimal("0.250"), True),
    ]
    # 07:00-08:30 (1.5) and 08:45-09:00 (0.25): the clocked day around the 08:30 break.
    assert _swept(general_work, worker) == [
        ("07:00:00", "08:30:00", Decimal("1.500")),
        ("08:45:00", "09:00:00", Decimal("0.250")),
    ]


def test_Q10_a_paid_break_added_inside_the_overtime_line_is_paid_ordinary(
    worker: Staff, job: Job
) -> None:
    """A paid break added inside an overtime line: accepted and paid ordinary on the Break
    job; the split stands.

    Guards attendance._create_break (a paid break is ordinary) and attendance.add_break
    (touches no entry).
    """
    _clock(worker, "07:00", "17:00")
    _book(worker, job, "07:00", "17:00")

    attendance.add_break(worker, DAY, time(16, 15), time(16, 30), paid=True, actor=worker)

    late_break = _break_at(worker, "16:15")
    # Ordinary: 1.0x of the 48.00 wage.
    assert (late_break.meta["wage_rate_multiplier"], late_break.unit_cost) == (
        1.0,
        Decimal("48.00"),
    )
    assert _on(job, worker) == [
        ("07:00:00", "16:00:00", Decimal("8.000"), 1.0),
        ("16:00:00", "17:00:00", Decimal("1.000"), 1.5),
    ]
    # 8 + 1 on the job + 0.25 + 0.25 + 0.25 paid breaks = 9.75.
    assert _paid(worker) == Decimal("9.75")


def test_Q11_lunch_deleted_inside_an_old_short_entry_leaves_its_hours(
    worker: Staff, job: Job
) -> None:
    """A legacy 07:00-15:00 entry holding 4h, and the lunch inside it is deleted: the
    break changes no entry, so it keeps its 4h.

    Guards attendance.remove_break (changes no entry).
    """
    _clock(worker, "07:00", "15:00")
    # Legacy data: hours saved as typed before the hours rule.
    old = make_time_line(
        job,
        worker,
        accounting_date=DAY,
        hours="4.000",
        approved=False,
        start_time="07:00:00",
        end_time="15:00:00",
    )

    attendance.remove_break(_break_at(worker, "11:30").id, worker)

    assert _entry(old.id) == ("07:00:00", "15:00:00", Decimal("4.000"), 1.0)
    assert _breaks(worker) == [
        ("08:30:00", "08:45:00", Decimal("0.250"), True),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]


# ── W. Entering it ──────────────────────────────────────────────────────


def test_W5_a_whole_hour_over_the_planned_break_keeps_the_break_off_the_day(
    worker: Staff, job: Job
) -> None:
    """The entry 08:00-09:00 saved as a whole hour on a day nobody clocked is accepted
    (hours never exceed the span). When the day gets its times, the 08:30 standard break
    has no room in it and is not recorded; lunch and 13:30 are. The hour is paid once.

    Guards attendance.generate_default_breaks (a standard break goes only where there is room).
    """
    # A whole hour, as the grid or an older drawer saved it: 1.0h within a 1.0h span.
    workshop_timesheet_service.create_entry(
        worker,
        worker,
        {
            "job_id": job.id,
            "accounting_date": DAY,
            "hours": Decimal("1"),
            "start_time": time(8, 0),
            "end_time": time(9, 0),
            "wage_rate_multiplier": Decimal("1.0"),
        },
    )

    _clock(worker, "07:00", "15:00")

    # 1.0h exceeds its span less the 08:30 break (60 - 15 = 45 minutes): no room.
    assert _on(job, worker) == [("08:00:00", "09:00:00", Decimal("1.000"), 1.0)]
    assert _breaks(worker) == [
        ("11:30:00", "12:00:00", Decimal("0.500"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]
    # 1.0 on the job + 0.25 (13:30); lunch unpaid = 1.25.
    assert _paid(worker) == Decimal("1.25")


def test_W6_an_entry_placed_around_the_planned_break_keeps_the_break(
    worker: Staff, job: Job
) -> None:
    """An entry 07:00-11:15 of 4h, placed around the planned 08:30 break on a day nobody
    clocked: when the day gets its times the paid break is recorded, and the entry keeps 4h.

    Guards attendance.generate_default_breaks (an entry with room keeps its break).
    """
    # Unclocked: the drawer places around the planned breaks, 255 - 15 = 240 = 4.0h.
    x = _book(worker, job, "07:00", "11:15")

    _clock(worker, "07:00", "15:00")

    # 4.0h is exactly its span less the 08:30 break: there is room, so it is recorded.
    assert _entry(x) == ("07:00:00", "11:15:00", Decimal("4.000"), 1.0)
    assert _breaks(worker) == [
        ("08:30:00", "08:45:00", Decimal("0.250"), True),
        ("11:30:00", "12:00:00", Decimal("0.500"), False),
        ("13:30:00", "13:45:00", Decimal("0.250"), True),
    ]
    # 4.0 + 0.25 + 0.25 = 4.5.
    assert _paid(worker) == Decimal("4.5")
