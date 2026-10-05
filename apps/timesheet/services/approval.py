"""Office approval of worked time (KAN-376).

Staff are paid for approved time only. A worker's own entry arrives
unapproved; any office staff member approves it, one entry at a time or a
person's whole day at once. Nothing is sent back and nothing is un-approved:
the office corrects an entry and phones the worker.

The Approve time screen is for office staff who are not shown pay, so nothing
this module returns carries a rate, a cost or a revenue figure.
"""

from datetime import date
from typing import Literal, TypedDict

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services.attendance import AttendanceData, attendance_data
from apps.timesheet.services.timesheet_events import record_timesheet_event, snapshot_if_entry
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopEntryData,
    entered_late,
    entry_data,
)

#: What a person's day needs from the office. ``nothing_entered`` is its own
#: state, not zero waiting: an empty day is the one the office phones about.
ApprovalState = Literal["waiting", "nothing_entered", "nothing_waiting"]

#: Rows open on what needs doing: time to approve, then people with nothing
#: in, then days already dealt with.
_STATE_ORDER: dict[ApprovalState, int] = {"waiting": 0, "nothing_entered": 1, "nothing_waiting": 2}


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
    entries: list[WorkshopEntryData]


class ApprovalsDayData(TypedDict):
    """Everyone's day, for the Approve time screen."""

    date: date
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
    person: Staff, lines: list[CostLine], attendance: AttendanceDay | None
) -> StaffApprovalData:
    waiting = [line for line in lines if not line.approved]
    state: ApprovalState
    if waiting:
        state = "waiting"
    elif lines:
        state = "nothing_waiting"
    else:
        state = "nothing_entered"
    return {
        "staff_id": str(person.id),
        "staff_name": person.get_display_full_name(),
        "state": state,
        "entered_hours": float(sum(line.quantity for line in lines)),
        "waiting_hours": float(sum(line.quantity for line in waiting)),
        "entered_late": any(entered_late(line) for line in waiting),
        "remote_entry": any(line.remote_entry for line in waiting),
        "clock": attendance_data(attendance),
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
    clocked = {row.staff_id: row for row in AttendanceDay.objects.filter(date=day)}
    rows = [
        _staff_day(person, by_staff.get(str(person.id), []), clocked.get(person.id))
        for person in get_displayable_staff(target_date=day)
    ]
    rows.sort(key=lambda row: (_STATE_ORDER[row["state"]], row["staff_name"]))
    return {"date": day, "staff": rows}
