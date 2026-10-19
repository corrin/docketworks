"""Office approval of worked time (KAN-376).

Staff are paid for approved time only. A worker's own entry arrives
unapproved; any office staff member approves it, one entry at a time or a
person's whole day at once. Nothing is sent back and nothing is un-approved:
the office corrects an entry and phones the worker.

The Approve time screen is for office staff who are not shown pay, so nothing
this module returns carries a rate, a cost or a revenue figure.
"""

from datetime import date, time
from decimal import Decimal
from typing import Literal, TypedDict
from uuid import UUID

from django.db import transaction
from django.utils.translation import gettext

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.errors import ConflictError
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.job.services.time_entry_rates import is_unpaid_time
from apps.timesheet.models import AttendanceDay
from apps.timesheet.services import hour_categories
from apps.timesheet.services.attendance import (
    AttendanceData,
    BreakData,
    Window,
    attendance_data,
    day_breaks,
    duration_words,
    fill_figures,
    hours_for,
    split_breaks,
    standard_day,
    unallocated_windows,
)
from apps.timesheet.services.location import saved_remotely
from apps.timesheet.services.timesheet_events import record_timesheet_event, snapshot_if_entry
from apps.timesheet.services.workshop_timesheet_service import (
    StandardDayData,
    WorkshopEntryData,
    create_entry,
    day_time_lines,
    default_entry_start,
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
    #: Clocked time on no job and no paid break: what a sweep would put on
    #: General work (KAN-380). None until both clock times are known.
    unallocated_hours: float | None
    breaks: list[BreakData]
    entries: list[WorkshopEntryData]
    #: Where an entry the office adds for this person starts: after their
    #: latest, else their clock-in, else the standard start; the rule their
    #: own day read uses.
    default_entry_start: time


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
    record_timesheet_event(
        staff=actor,
        event_type="entry_approved",
        line=line,
        before=before,
        trusted=not saved_remotely(actor, None),
    )


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
    person: Staff,
    day: date,
    lines: list[CostLine],
    attendance: AttendanceDay | None,
    *,
    rostered: bool,
) -> StaffApprovalData:
    # Lunch is logged, not hours: it is in no figure and does not by itself
    # hold a row waiting. Approving the day approves it with the rest.
    hours = [line for line in lines if not is_unpaid_time(line)]
    waiting = [line for line in hours if not line.approved]
    entries, break_lines = split_breaks(lines)
    clock = attendance_data(attendance)
    fill = fill_figures(
        attendance, sum((line.quantity for line in entries), Decimal(0)), break_lines
    )
    unallocated = unallocated_windows(day, attendance, entries, break_lines)
    if fill is not None and fill["to_go_hours"] < 0:
        # More entered than he was here for. The usual cause: he clocked, so
        # his paid breaks were entered, and a full day of jobs was typed too.
        over = duration_words(Decimal(str(-fill["to_go_hours"])))
        clock = {
            **clock,
            "cautions": [*clock["cautions"], gettext("Over by %(over)s") % {"over": over}],
        }
    state: ApprovalState
    if not entries and (rostered or attendance is not None):
        # Expected and no job in: the person the office phones. His paid
        # breaks, entered when he clocked out, do not make a day entered.
        state = "nothing_entered"
    elif not entries:
        state = "not_rostered"
    elif waiting:
        state = "waiting"
    else:
        # Leave is here too: its line is approved when it is made.
        state = "nothing_waiting"
    return {
        "staff_id": str(person.id),
        "staff_name": person.get_display_full_name(),
        "state": state,
        "entered_hours": float(sum(line.quantity for line in hours)),
        "waiting_hours": float(sum(line.quantity for line in waiting)),
        "entered_late": any(entered_late(line) for line in waiting),
        "remote_entry": any(line.remote_entry for line in waiting),
        "clock": clock,
        "unallocated_hours": None if unallocated is None else float(_hours_in(unallocated)),
        "breaks": day_breaks(attendance.date, attendance, break_lines)
        if attendance is not None
        else [],
        # His paid breaks travel as breaks, with lunch: nobody reading a day
        # is shown that the two kinds are stored differently.
        "entries": [entry_data(line) for line in entries],
        "default_entry_start": default_entry_start(day, attendance, entries, break_lines),
    }


def day_approvals(day: date) -> ApprovalsDayData:
    """Everyone on the day's timesheet with what they entered and what is waiting.

    The people are the ones the daily timesheet lists, including anyone with
    nothing entered. One query for the day's lines, grouped here.
    """
    by_staff: dict[str, list[CostLine]] = {}
    lines = CostLine.objects.filter(
        cost_set__kind="actual", kind="time", accounting_date=day
    ).select_related("cost_set__job__company", "xero_pay_item")
    for line in lines:
        by_staff.setdefault(str(line.staff_id), []).append(line)
    clocked = {row.staff_id: row for row in AttendanceDay.objects.filter(date=day)}
    weekend_enabled = CompanyDefaults.get_solo().weekend_timesheets_enabled
    rows = [
        _staff_day(
            person,
            day,
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


# ── Sweep (KAN-380) ─────────────────────────────────────────────────────

#: Why a person's day was not swept. Both mean there is no clocked time to
#: speak of: the sweep reads clock times as they stand and never sets one.
SweepSkipReason = Literal["still_clocked_in", "no_clock_times"]


class SweepSkipData(TypedDict):
    """A day the sweep left alone, for the office to deal with."""

    staff_id: str
    staff_name: str
    date: date
    reason: SweepSkipReason


class SweepData(TypedDict):
    """What a sweep moved onto General work and approved."""

    swept_hours: float
    #: The worker's own entries the sweep approved with the day.
    approved_count: int
    skipped: list[SweepSkipData]


class GeneralWorkNotSetUpError(ConflictError):
    """The instance has no General work job, so there is nowhere to sweep to."""


@transaction.atomic
def sweep_person(worker: Staff, days: list[date], actor: Staff) -> SweepData:
    """Sweep one person's days: their clocked time on no job goes onto General work."""
    return _sweep({day: [worker] for day in days}, actor)


@transaction.atomic
def sweep_everyone(days: list[date], actor: Staff) -> SweepData:
    """Sweep the days of everyone who clocked or has time on them."""
    return _sweep({day: _people_on(day) for day in days}, actor)


def _people_on(day: date) -> list[Staff]:
    """Return the people who clocked or have time on the day.

    Someone with neither has nothing to sweep and nothing to approve, so they
    are not reported as skipped.
    """
    present = set(AttendanceDay.objects.filter(date=day).values_list("staff_id", flat=True))
    present |= set(
        CostLine.objects.filter(
            cost_set__kind="actual", kind="time", accounting_date=day
        ).values_list("staff_id", flat=True)
    )
    return [person for person in get_displayable_staff(target_date=day) if person.id in present]


def _sweep(people_by_day: dict[date, list[Staff]], actor: Staff) -> SweepData:
    """Sweep each person's day, approving what it sweeps; skip days with no clocked time.

    Sweeping is approving (owner, 2026-10-17): the office saw the day and
    accepted it, so the worker's own waiting entries are approved with it.
    """
    general_work_id = CompanyDefaults.get_solo().general_work_job_id
    if general_work_id is None:
        raise GeneralWorkNotSetUpError(
            gettext(
                "General work isn't set up: there is no General work job yet. Ask an administrator "
                "to choose it in Company Defaults > Working Hours."
            )
        )
    # Two offices sweeping the same person would both read the same stretches
    # before either writes, and pay them twice; the second waits here and
    # reads the first's entries. Ordered by pk so two sweeps never deadlock.
    staff_ids = {person.pk for people in people_by_day.values() for person in people}
    list(Staff.objects.select_for_update().filter(pk__in=staff_ids).order_by("pk"))
    swept = Decimal(0)
    approved = 0
    skipped: list[SweepSkipData] = []
    for day, people in people_by_day.items():
        for person in people:
            row = AttendanceDay.objects.filter(staff=person, date=day).first()
            entries, break_lines = split_breaks(day_time_lines(person, day))
            windows = unallocated_windows(day, row, entries, break_lines)
            if windows is None:
                skipped.append(
                    {
                        "staff_id": str(person.id),
                        "staff_name": person.get_display_full_name(),
                        "date": day,
                        "reason": "no_clock_times" if row is None else "still_clocked_in",
                    }
                )
            else:
                swept += _put_on_general_work(person, day, windows, general_work_id, actor)
                approved += approve_day(person, day, actor)
    return {"swept_hours": float(swept), "approved_count": approved, "skipped": skipped}


def _put_on_general_work(
    worker: Staff, day: date, windows: list[Window], general_work_id: UUID, actor: Staff
) -> Decimal:
    """Make a General work entry in each stretch on no job; return the hours they hold.

    One entry per stretch, ending where a break or a real entry starts and
    starting again where it ends. Entered by the office, so each starts
    approved. No stretches (his entries cover the day, or more) moves nothing,
    and the day is still approved.
    """
    for window in windows:
        create_entry(
            actor,
            worker,
            {
                "job_id": general_work_id,
                "accounting_date": day,
                "hours": hours_for(window.start, window.end, []),
                "start_time": window.start,
                "end_time": window.end,
                # A shop job's time is billed to nobody; the model refuses otherwise.
                "is_billable": False,
            },
        )
    return _hours_in(windows)


def _hours_in(windows: list[Window]) -> Decimal:
    """Return the hours the stretches hold: each one's stop less its start."""
    return sum((hours_for(window.start, window.end, []) for window in windows), Decimal(0))
