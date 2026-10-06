"""Office approval of worked time (KAN-376).

Staff are paid for approved time only. A worker's own entry arrives
unapproved; any office staff member approves it, one entry at a time or a
person's whole day at once. Nothing is sent back and nothing is un-approved:
the office corrects an entry and phones the worker.

The Approve time screen is for office staff who are not shown pay, so nothing
this module returns carries a rate, a cost or a revenue figure.
"""

from datetime import date, time
from typing import Literal, TypedDict

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import hour_categories
from apps.timesheet.services.attendance import (
    AttendanceData,
    BreakData,
    attendance_data,
    break_data,
    day_breaks,
    default_entry_start,
    standard_day,
)
from apps.timesheet.services.timesheet_events import record_timesheet_event, snapshot_if_entry
from apps.timesheet.services.workshop_timesheet_service import (
    StandardDayData,
    WorkshopEntryData,
    entered_late,
    entry_data,
)

#: What a person's day needs from the office. ``nothing_entered`` is its own
#: state, not zero waiting: an empty day is the one the office phones about.
ApprovalState = Literal["waiting", "nothing_entered", "nothing_waiting", "not_rostered"]

#: How the whole day stands. ``nobody_rostered`` is not ``complete``: a Sunday
#: with nobody expected has nothing to finish.
DayStanding = Literal["in_progress", "complete", "nobody_rostered"]

#: Rows open on what needs doing: time to approve, then people with nothing
#: in, then days already dealt with.
_STATE_ORDER: dict[ApprovalState, int] = {
    "waiting": 0,
    "nothing_entered": 1,
    "nothing_waiting": 2,
    "not_rostered": 3,
}


class StaffApprovalData(TypedDict):
    """One person's day as the office approves it."""

    staff_id: str
    staff_name: str
    state: ApprovalState
    entered_hours: float
    waiting_hours: float
    #: Any waiting entry was made after its day, or away from the workshop.
    entered_late: bool
    remote_entry: bool
    #: Whether the person was here, a separate question from whether their
    #: time is approved: every pairing of the two is an ordinary day.
    clock: AttendanceData
    breaks: list[BreakData]
    entries: list[WorkshopEntryData]


class DaySummaryData(TypedDict):
    """How the day stands across the people expected on it.

    Every day is finished on the day (owner, 2026-10-06), so the screen says
    how far along today is. Only people expected count: someone not rostered
    with nothing on the day is left out, or no day could ever read complete.
    """

    expected: int
    approved: int
    standing: DayStanding


class ApprovalsDayData(TypedDict):
    """Everyone's day, for the Approve time screen."""

    date: date
    #: The company's standard hours for the date; None on a weekend.
    standard: StandardDayData | None
    default_entry_start: time
    summary: DaySummaryData
    staff: list[StaffApprovalData]


def approve_line(line: CostLine, actor: Staff) -> None:
    """Approve a line the caller holds locked, and record who did.

    The caller has taken the costing lock on the line's job and the row lock
    on the line, and has refused a workflow-managed or already approved line.
    """
    before = snapshot_if_entry(line)
    line.approved = True
    line.save(update_fields=["approved", "updated_at"])
    record_timesheet_event(staff=actor, event_type="entry_approved", line=line, before=before)


def approve_day(worker: Staff, day: date, actor: Staff) -> int:
    """Approve every entry of one person's day that is waiting; return how many.

    Zero is an ordinary answer: two office staff pressing approve on the same
    person is not an error. Leave and other workflow-managed lines are not
    touched; they are approved when they are made.
    """
    waiting = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
        staff=worker,
        accounting_date=day,
        approved=False,
        managed_by=None,
    )
    lock_costing_jobs(set(waiting.values_list("cost_set__job_id", flat=True)))
    # Locked on the line alone: the snapshot's joins are nullable, which
    # Postgres refuses under FOR UPDATE. Read again under the locks, so a line
    # approved or moved in between is not approved twice.
    locked = list(
        waiting.select_for_update(of=("self",)).select_related(
            "cost_set__job", "labour_subtype", "xero_pay_item"
        )
    )
    for line in locked:
        approve_line(line, actor)
    return len(locked)


def _staff_day(
    person: Staff, lines: list[CostLine], attendance: AttendanceDay | None, *, rostered: bool
) -> StaffApprovalData:
    waiting = [line for line in lines if not line.approved]
    state: ApprovalState
    if waiting:
        state = "waiting"
    elif lines:
        # Leave is here too: its line is approved when it is made.
        state = "nothing_waiting"
    elif rostered or attendance is not None:
        # Expected and nothing in: the person the office phones.
        state = "nothing_entered"
    else:
        state = "not_rostered"
    return {
        "staff_id": str(person.id),
        "staff_name": person.get_display_full_name(),
        "state": state,
        "entered_hours": float(sum(line.quantity for line in lines)),
        "waiting_hours": float(sum(line.quantity for line in waiting)),
        "entered_late": any(entered_late(line) for line in waiting),
        "remote_entry": any(line.remote_entry for line in waiting),
        "clock": attendance_data(attendance),
        "breaks": [break_data(each) for each in day_breaks(attendance)],
        "entries": [entry_data(line) for line in lines],
    }


def day_approvals(day: date) -> ApprovalsDayData:
    """Everyone on the day's timesheet with what they entered and what is waiting.

    The people are the ones the daily timesheet lists, including anyone with
    nothing entered. One query for the day's lines, grouped here.
    """
    by_staff: dict[str, list[CostLine]] = {}
    lines = CostLine.objects.filter(
        cost_set__kind="actual", kind="time", accounting_date=day
    ).select_related("cost_set__job__company")
    for line in lines:
        by_staff.setdefault(str(line.staff_id), []).append(line)
    clocked = {
        row.staff_id: row
        for row in AttendanceDay.objects.filter(date=day).prefetch_related("breaks")
    }
    weekend_enabled = CompanyDefaults.get_solo().weekend_timesheets_enabled
    rows = [
        _staff_day(
            person,
            by_staff.get(str(person.id), []),
            clocked.get(person.id),
            # The roster rule the daily and weekly screens use.
            rostered=hour_categories.scheduled_hours(person, day, weekend_enabled=weekend_enabled)
            > 0,
        )
        for person in get_displayable_staff(target_date=day)
    ]
    rows.sort(key=lambda row: (_STATE_ORDER[row["state"]], row["staff_name"]))
    standard = standard_day(day)
    return {
        "date": day,
        "standard": None if standard is None else {"start": standard.start, "end": standard.end},
        "default_entry_start": default_entry_start(day),
        "summary": day_summary(rows),
        "staff": rows,
    }


def day_summary(rows: list[StaffApprovalData]) -> DaySummaryData:
    """Count the people expected on the day and those with nothing left to approve."""
    expected = [row for row in rows if row["state"] != "not_rostered"]
    approved = sum(1 for row in expected if row["state"] == "nothing_waiting")
    standing: DayStanding
    if not expected:
        standing = "nobody_rostered"
    elif approved == len(expected):
        standing = "complete"
    else:
        standing = "in_progress"
    return {"expected": len(expected), "approved": approved, "standing": standing}
