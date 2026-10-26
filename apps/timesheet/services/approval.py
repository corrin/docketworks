"""Office approval of worked time (KAN-376).

Staff are paid for approved time only. A worker's own entry arrives
unapproved; any office staff member approves it, one entry at a time or a
person's whole day at once. Nothing is sent back and nothing is un-approved:
the office corrects an entry and phones the worker.

The Approve time screen is for office staff who are not shown pay, so nothing
this module returns carries a rate, a cost or a revenue figure.
"""

from datetime import date, time, timedelta
from decimal import Decimal
from typing import Literal, TypedDict
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.errors import ConflictError, InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.enums import CostLineOwner
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.job.services.time_entry_rates import is_unpaid_time
from apps.timesheet.models import AttendanceDay, LeaveType
from apps.timesheet.services import hour_categories
from apps.timesheet.services.attendance import (
    AttendanceData,
    BreakData,
    Window,
    attendance_data,
    break_job_id,
    day_breaks,
    duration_words,
    fill_figures,
    hours_for,
    split_breaks,
    standard_day,
    unallocated_windows,
    use_standard_hours,
)
from apps.timesheet.services.location import saved_remotely
from apps.timesheet.services.timesheet_events import (
    record_day_event,
    record_timesheet_event,
    snapshot_if_entry,
)
from apps.timesheet.services.workshop_timesheet_service import (
    SMALLEST_SPLIT,
    StandardDayData,
    WorkshopEntryData,
    day_time_lines,
    default_entry_start,
    entered_late,
    entry_data,
    fill_with_general_work,
    on_a_public_holiday,
    overtime_hours,
)
from apps.timesheet.services.xero_hours import leave_job_ids

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
    #: His hours at overtime are not the hours past his usual day: the
    #: office checks which time it is (owner, 2026-10-25).
    overtime_check: bool
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
    # The person first, then the jobs: the order the sweep and every write to
    # his day take them in, so none of them waits on another in a circle.
    Staff.objects.select_for_update().filter(pk=worker.pk).first()
    waiting = _waiting(worker, day)
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


def _waiting(worker: Staff, day: date) -> QuerySet[CostLine]:
    """His entries for the day the office has still to approve; leave is approved when made."""
    return CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
        staff=worker,
        accounting_date=day,
        approved=False,
        managed_by=None,
    )


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
    # Nobody clocked: a day gone by he was rostered for is the standard day.
    unallocated = (
        unallocated_windows(day, attendance, entries, break_lines)
        if attendance is not None
        or (rostered and day < timezone.localdate() and not _has_leave(entries))
        else None
    )
    if fill is not None and fill["to_go_hours"] < 0:
        # More entered than he was here for. The usual cause: he clocked, so
        # his paid breaks were entered, and a full day of jobs was typed too.
        over = duration_words(Decimal(str(-fill["to_go_hours"])))
        clock = {
            **clock,
            "cautions": [*clock["cautions"], gettext("Over by %(over)s") % {"over": over}],
        }
    if _has_leave(entries) and any(line.managed_by != CostLineOwner.LEAVE for line in entries):
        # Paid for both: he came in on a day off, or the leave is wrong.
        clock = {
            **clock,
            "cautions": [*clock["cautions"], gettext("Leave and work on the same day")],
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
        "overtime_check": _overtime_is_off(person, day, entries),
        "breaks": day_breaks(attendance.date, attendance, break_lines)
        if attendance is not None
        else [],
        # His paid breaks travel as breaks, with lunch: nobody reading a day
        # is shown that the two kinds are stored differently.
        "entries": [entry_data(line) for line in entries],
        "default_entry_start": default_entry_start(day, attendance, entries, break_lines),
    }


def _overtime_is_off(person: Staff, day: date, entries: list[CostLine]) -> bool:
    """Whether his time at overtime is other than the hours past his usual day.

    An entry deleted after its overtime half was split off, or a lunch he
    worked through and added back as ordinary time, leaves the two apart;
    nothing re-rates them, so the office is shown the day to check. Less
    than a quarter hour apart is the split rule keeping a few minutes whole,
    not a day to check.
    """
    leave = leave_job_ids()
    work = [
        line for line in entries if line.cost_set.job_id not in leave and not is_unpaid_time(line)
    ]
    worked = sum((line.quantity for line in work), Decimal(0))
    at_overtime = sum(
        (line.quantity for line in work if hour_categories.wage_rate_multiplier(line) > 1),
        Decimal(0),
    )
    expected = overtime_hours(person, day, worked, already_on_the_day=False)
    return abs(at_overtime - expected) >= SMALLEST_SPLIT


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
            rostered=_rostered(person, day, weekend_enabled=weekend_enabled),
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


class SweepOvertimeData(TypedDict):
    """A day the sweep took past the usual day, so some of it went to overtime."""

    staff_id: str
    staff_name: str
    message: str


class SweepData(TypedDict):
    """What a sweep moved onto General work, and the days it left alone."""

    swept_hours: float
    skipped: list[SweepSkipData]
    #: Days it put past the usual day: the office checks which time is overtime.
    overtime: list[SweepOvertimeData]


class GeneralWorkNotSetUpError(ConflictError):
    """The instance has no usable General work job, so there is nowhere to sweep to."""


def _general_work_job_id() -> UUID:
    """Return the job the sweep books to, refusing one that is not worked time.

    Pointed at Break, swept time would read as breaks; pointed at a leave job,
    it would post to Xero as leave and draw down balances. Company Defaults
    cannot refuse either when it is saved: the core app knows nothing of
    breaks or leave, so the sweep refuses before it writes anything.
    """
    general_work = CompanyDefaults.get_solo().general_work_job
    if general_work is None:
        raise GeneralWorkNotSetUpError(
            gettext(
                "General work isn't set up: there is no General work job yet. Ask an administrator "
                "to choose it in Company Defaults > Working Hours."
            )
        )
    if general_work.id == break_job_id() or LeaveType.objects.filter(job=general_work).exists():
        raise GeneralWorkNotSetUpError(
            gettext(
                "General work is set to %(job)s, which is for breaks or leave, not worked time. "
                "Ask an administrator to choose another job in Company Defaults > Working Hours."
            )
            % {"job": general_work.name}
        )
    return general_work.id


#: The longest stretch one sweep takes: the weekly overview's week.
SWEEP_MOST_DAYS = 7


def sweep_days(start: date, end: date) -> list[date]:
    """Return the days from ``start`` to ``end``, refusing a range the sweep must not take.

    A day after today has not been worked: sweeping it would approve office-set
    clock times as paid time nobody has done yet. Today is allowed, since a
    person who has clocked out is done. A week is the most a sweep holds its
    lock on everyone's day for.
    """
    if end < start:
        raise InvalidInputError(gettext("The end date is before the start date."))
    if end > timezone.localdate():
        raise InvalidInputError(
            gettext("Days after today haven't been worked yet, so they can't be swept.")
        )
    if (end - start).days >= SWEEP_MOST_DAYS:
        raise InvalidInputError(gettext("A sweep covers one week at most."))
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


@transaction.atomic
def sweep_person(worker: Staff, days: list[date], actor: Staff) -> SweepData:
    """Sweep one person's days: their clocked time on no job goes onto General work."""
    return _sweep({day: [worker] for day in days}, actor)


@transaction.atomic
def sweep_everyone(days: list[date], actor: Staff) -> SweepData:
    """Sweep the days of everyone who clocked or has time on them."""
    return _sweep({day: _people_on(day) for day in days}, actor)


def _rostered(person: Staff, day: date, *, weekend_enabled: bool) -> bool:
    """Whether he was expected on the day, by the roster rule the timesheet screens use."""
    return hour_categories.scheduled_hours(person, day, weekend_enabled=weekend_enabled) > 0


def _has_leave(entries: list[CostLine]) -> bool:
    """Whether he took leave on the day."""
    return any(line.managed_by == CostLineOwner.LEAVE for line in entries)


def _assumed_standard(
    person: Staff,
    day: date,
    row: AttendanceDay | None,
    entries: list[CostLine],
    *,
    weekend_enabled: bool,
) -> bool:
    """Whether his day is the standard day because he did not clock (owner, 2026-10-21).

    Only a day gone by: today he may still clock in. Not a day with leave: the
    standard times it would be given are clocked time, which leave takes none
    of, so a second sweep would book his leave hours again; the office sets
    that day's times.
    """
    return (
        row is None
        and person.is_active_on(day)
        and day < timezone.localdate()
        and not _has_leave(entries)
        and _rostered(person, day, weekend_enabled=weekend_enabled)
    )


def _people_on(day: date) -> list[Staff]:
    """Return the people who clocked, have time on the day, or were rostered for it.

    Someone with none of these has nothing to sweep and nothing to approve, so
    they are not reported as skipped. Someone rostered who did not clock
    worked the standard day.
    """
    weekend_enabled = CompanyDefaults.get_solo().weekend_timesheets_enabled
    present = set(AttendanceDay.objects.filter(date=day).values_list("staff_id", flat=True))
    present |= set(
        CostLine.objects.filter(
            cost_set__kind="actual", kind="time", accounting_date=day
        ).values_list("staff_id", flat=True)
    )
    return [
        person
        for person in get_displayable_staff(target_date=day)
        if person.id in present
        # Not present: he has no lines on the day.
        or _assumed_standard(person, day, None, [], weekend_enabled=weekend_enabled)
    ]


def _sweep(people_by_day: dict[date, list[Staff]], actor: Staff) -> SweepData:
    """Sweep each person's day onto General work, then approve it; skip days with no clocked time.

    Approve time's shortcut: two operations in one press (owner, 2026-10-26:
    "Sweep isn't exactly approval. Under approve we have a convenience
    shortcut - sweep and approve"). The sweep enters the General work, which
    waits like any entry, and approving the day approves it with the rest.
    """
    general_work_id = _general_work_job_id()
    # Two offices sweeping the same person would both read the same stretches
    # before either writes, and pay them twice; the second waits here and
    # reads the first's entries. Ordered by pk so two sweeps never deadlock.
    # Every write to a person's day takes his lock first, so his entries and
    # clock times stand still until the sweep commits.
    staff_ids = {person.pk for people in people_by_day.values() for person in people}
    list(Staff.objects.select_for_update().filter(pk__in=staff_ids).order_by("pk"))
    # Every job the sweep will write to, at once and in id order: taken one
    # call at a time they could cross another writer's order and deadlock.
    job_ids = {general_work_id}
    # Standard hours put the standard breaks on an unclocked day.
    break_id = break_job_id()
    if break_id is not None:
        job_ids.add(break_id)
    for day, people in people_by_day.items():
        for person in people:
            job_ids |= set(_waiting(person, day).values_list("cost_set__job_id", flat=True))
    lock_costing_jobs(job_ids)
    swept = Decimal(0)
    skipped: list[SweepSkipData] = []
    overtime: list[SweepOvertimeData] = []
    weekend_enabled = CompanyDefaults.get_solo().weekend_timesheets_enabled
    for day, people in people_by_day.items():
        for person in people:
            row = AttendanceDay.objects.filter(staff=person, date=day).first()
            entries, break_lines = split_breaks(day_time_lines(person, day))
            # Not clocking in is working the standard day (owner, 2026-10-21).
            assumed = _assumed_standard(person, day, row, entries, weekend_enabled=weekend_enabled)
            windows = (
                unallocated_windows(day, row, entries, break_lines)
                if row is not None or assumed
                else None
            )
            if windows is None:
                skipped.append(
                    {
                        "staff_id": str(person.id),
                        "staff_name": person.get_display_full_name(),
                        "date": day,
                        "reason": "no_clock_times" if row is None else "still_clocked_in",
                    }
                )
                continue
            if assumed and windows:
                # Recorded as the office's, so the day says it was not clocked;
                # its standard breaks are the ones the stretches were placed around.
                use_standard_hours(person, day, actor)
                row = AttendanceDay.objects.get(staff=person, date=day)
            if _goes_past_the_usual_day(person, day, windows):
                overtime.append(_overtime_warning(person, day))
            if row is None:
                # Unclocked and his leave fills the standard day: nothing to
                # fill and no day to send, but his entries are approved.
                approve_day(person, day, actor)
                continue
            swept += fill_with_general_work(person, day, actor)
            approve_day(person, day, actor)
            _send_for_him(person, row, actor)
    return {
        "swept_hours": float(swept),
        "skipped": skipped,
        "overtime": overtime,
    }


def _goes_past_the_usual_day(worker: Staff, day: date, windows: list[Window]) -> bool:
    """Whether the General work the sweep is about to book takes his day past the usual day."""
    return overtime_hours(worker, day, _hours_in(windows)) > 0


def _overtime_warning(worker: Staff, day: date) -> SweepOvertimeData:
    """Tell the office the sweep put some of his day at time and a half (owner, 2026-10-25).

    The overtime lands on whichever time the sweep books past the usual day,
    which may be his morning: he marks his own late time, and the office
    checks which hours it was.
    """
    name = worker.get_display_name()
    if on_a_public_holiday(worker, day):
        # Every hour of it is time and a half, however few.
        message = gettext(
            "%(name)s worked a public holiday, so that time is at time and a half."
        ) % {"name": name}
    else:
        standard = standard_day(day)
        if standard is None:
            raise ValueError(f"{day} has no usual day, so nothing on it is overtime")
        usual = duration_words(hours_for(standard.start, standard.end, []))
        message = gettext("%(name)s has done over %(usual)s, converting some time to overtime.") % {
            "name": name,
            "usual": usual,
        }
    return {
        "staff_id": str(worker.id),
        "staff_name": worker.get_display_full_name(),
        "message": message,
    }


def _send_for_him(worker: Staff, row: AttendanceDay, actor: Staff) -> None:
    """Mark a swept day sent, as the office has now filled and accepted it.

    Left unsent, his app asks him to finish the day, and the rows he sent
    would be laid out after the General work and paid on top of it.
    """
    if row.submitted_at is not None:
        return
    row.submitted_at = timezone.now()
    row.save(update_fields=["submitted_at", "updated_at"])
    record_day_event(
        staff=actor,
        worker=worker,
        day=row.date,
        event_type="day_sent",
        before=None,
        after=None,
        trusted=True,
    )


def _hours_in(windows: list[Window]) -> Decimal:
    """Return the hours the stretches hold: each one's stop less its start."""
    return sum((hours_for(window.start, window.end, []) for window in windows), Decimal(0))
