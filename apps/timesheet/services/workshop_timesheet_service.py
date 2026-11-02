"""Workshop "my time" self-service for a staff member's own entries.

A staff member reads and writes their own entries; office staff may also read
and correct another person's (KAN-376: the office corrects an entry and phones
the worker, it does not send it back). Every write names two people: the
``actor`` who is saving and the ``owner`` whose time it is.

Rate resolution goes through the one pipeline in
``apps.job.services.time_entry_rates`` (ADR 0039). Resolving a pay item from the
wage multiplier alone is rejected because leave must use the job's leave pay
item and a zero bill rate.
"""

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext

from apps.accounts.models import Staff
from apps.core.errors import AccessDeniedError, ConflictError, InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.enums import CostLineOwner
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.job.services.job_service import (
    CostLineData,
    a_change_takes_the_approval_off,
    cost_line_data,
    get_or_create_cost_set,
    move_time_line,
    refuse_workflow_managed,
    update_latest_actual,
)
from apps.job.services.time_entry_rates import (
    UNPAID_TIME,
    ZERO_MULTIPLIER,
    normalize_multiplier,
    price_time_entry,
    rate_from_meta,
)
from apps.timesheet.models import (
    EDITED_STANDARD_BREAK,
    SWEPT_GENERAL_WORK,
    UNTOUCHED_STANDARD_BREAK,
    AttendanceDay,
    LeaveType,
    mark_break_edited,
)
from apps.timesheet.services import attendance, hour_categories
from apps.timesheet.services.attendance import (
    AttendanceData,
    BreakData,
    CalendarBounds,
    FillData,
    PendingDay,
)
from apps.timesheet.services.location import EntryLocation, saved_remotely
from apps.timesheet.services.timesheet_events import (
    record_day_event,
    record_timesheet_event,
    snapshot_if_entry,
)
from apps.timesheet.services.weekly_timesheet_service import PAYROLL_WEEK_DAYS, payroll_week_start
from apps.timesheet.services.xero_hours import leave_job_ids

logger = logging.getLogger(__name__)


class EntryOwnershipError(AccessDeniedError):
    """A staff member touched an entry that is not theirs (403 at the boundary)."""


def entry_owner(actor: Staff, staff_id: UUID | None) -> Staff:
    """Whose day the actor is asking for: their own unless office staff name another."""
    if staff_id is None or staff_id == actor.id:
        return actor
    if not actor.is_office_staff:
        raise EntryOwnershipError(gettext("Only office staff see or enter another person's time."))
    return Staff.objects.get(id=staff_id)


def _refuse_another_persons_entry(line: CostLine, actor: Staff, refusal: str) -> None:
    """Refuse a change to someone else's entry by anyone but the office."""
    if line.meta.get("staff_id") != str(actor.id) and not actor.is_office_staff:
        raise EntryOwnershipError(refusal)


def _owner_of(line: CostLine) -> Staff:
    """Return the person whose time the line records; their wage prices it."""
    if line.staff is None:
        raise ValueError(f"Time line {line.id} has no staff member")
    return line.staff


class WorkshopEntryCreateData(TypedDict, total=False):
    """Validated create payload."""

    job_id: UUID
    accounting_date: date
    hours: Decimal
    description: str | None
    start_time: time | None
    end_time: time | None
    is_billable: bool
    wage_rate_multiplier: Decimal
    bill_rate_multiplier: Decimal
    #: The office grid's pick; the worker's default subtype when absent.
    labour_subtype_id: UUID


class WorkshopEntryUpdateData(TypedDict, total=False):
    """Validated partial update payload."""

    entry_id: UUID
    job_id: UUID
    accounting_date: date
    hours: Decimal
    description: str | None
    start_time: time | None
    end_time: time | None
    is_billable: bool
    wage_rate_multiplier: Decimal
    bill_rate_multiplier: Decimal
    labour_subtype_id: UUID


class WorkshopEntryData(TypedDict):
    """Data contract for WorkshopEntryData."""

    id: str
    job_id: str
    job_number: int
    job_name: str
    company_name: str
    description: str
    hours: float
    accounting_date: date
    start_time: time | None
    end_time: time | None
    is_billable: bool
    wage_rate_multiplier: float
    bill_rate_multiplier: float
    approved: bool
    entered_late: bool
    remote_entry: bool
    created_at: datetime
    updated_at: datetime


class WorkshopSummaryData(TypedDict):
    """Data contract for WorkshopSummaryData."""

    total_hours: float
    billable_hours: float
    non_billable_hours: float


class WorkshopWeekData(TypedDict):
    """The payroll week's hours: what payroll will pay, and what is held back."""

    approved_hours: float
    waiting_hours: float


class StandardDayData(TypedDict):
    """The company's standard start and finish for a weekday."""

    start: time
    end: time


class WorkshopDayData(TypedDict):
    """Data contract for WorkshopDayData."""

    date: date
    entries: list[WorkshopEntryData]
    summary: WorkshopSummaryData
    week: WorkshopWeekData
    day: AttendanceData
    #: His breaks, drawn on the calendar; in no hours figure.
    breaks: list[BreakData]
    #: Hours to fill, entered and to go; None until both clock times are known.
    fill: FillData | None
    #: The company's standard hours for the date; None on a weekend.
    standard: StandardDayData | None
    #: The standard finish to offer for an earlier day left clocked in.
    missed_clock_out_finish: time | None
    #: Where a new entry opens when nothing on the day precedes it.
    default_entry_start: time
    calendar: CalendarBounds
    #: An earlier day the person clocked and has not sent.
    pending: PendingDay | None


def resolve_entry_date(date_param: str | None) -> date:
    """Parse the optional ``date`` query parameter; today when absent."""
    if not date_param:
        return timezone.localdate()
    parsed = parse_date(date_param)
    if parsed is None:
        raise ValueError(gettext("date must be provided in YYYY-MM-DD format."))
    return parsed


def _format_time(value: time | None) -> str | None:
    """ISO-format a time for storage in ``meta``."""
    return value.isoformat() if value is not None else None


def _meta_time(meta: dict[str, object], key: str) -> time | None:
    """Read a stored start/end time out of ``meta`` (ISO string) as a time."""
    value = meta.get(key)
    if not isinstance(value, str):
        return None
    return time.fromisoformat(value)


# Fable: Not exact equality: clients derive hours from the minute-grained time
# pair and round to two decimals, so a 20-minute booking is 0.33 hours against
# a 0.3333… duration. Rounding alone bounds the error at 0.005; the full 0.01
# is deliberate headroom, and at most 36 seconds of wage per entry.
_TIME_AGREEMENT_TOLERANCE = Decimal("0.01")


def _validate_time_consistency(
    day: date, start: time | None, end: time | None, hours: Decimal
) -> None:
    """Refuse a start/end pair that is backwards or too short to hold ``hours``.

    An entry's hours are what is paid and billed; its times are a picture of
    where the work sat in the day. Breaks are outside job time, so an entry
    spanning one has a span longer than its hours, and that is ordinary. What
    cannot be is more hours than the span. A single missing time carries no
    span and is exempt.
    """
    if start is None or end is None:
        return
    if end <= start:
        raise ValueError(gettext("The finish time must be after the start time."))
    elapsed = datetime.combine(date.min, end) - datetime.combine(date.min, start)
    # The night the clocks go back, an hour more passes than the clock shows.
    minutes = Decimal(elapsed.total_seconds()) / 60 + attendance.clock_change_minutes(
        day, start, end
    )
    duration = minutes / Decimal(60)
    if hours - duration > _TIME_AGREEMENT_TOLERANCE:
        raise ValueError(
            gettext(
                "hours (%(hours)s) cannot be more than the start_time-end_time span (%(span)s)."
            )
            % {"hours": hours, "span": duration.quantize(Decimal("0.01"))}
        )


def _meta_multiplier(meta: dict[str, object], key: str, default: Decimal) -> Decimal:
    """Read a multiplier out of ``meta``; unset falls back to ``default``.

    ``default`` covers absence only. A stored non-numeric value raises out of
    rate_from_meta: it used to land on this same default, so a corrupt
    multiplier was indistinguishable from an unset one.
    """
    raw = rate_from_meta(meta, key)
    if raw is None:
        return default
    return normalize_multiplier(raw)


#: Lines nobody typed, never marked entered late.
_GENERATED_SOURCES = frozenset(
    {UNTOUCHED_STANDARD_BREAK, EDITED_STANDARD_BREAK, SWEPT_GENERAL_WORK}
)


def entered_late(line: CostLine) -> bool:
    """Whether the entry was made on a later day than the day it is for.

    Entering time on the day is the rule, because nobody remembers
    yesterday's tasks (owner, 2026-10-06). Late entry is flagged, not blocked,
    whoever typed it. The comparison is in local dates: an entry made at 23:30
    for that day is on time. A line a workflow owns is never late: leave is
    routinely entered the day after.
    """
    if line.managed_by is not None or line.meta.get("source") in _GENERATED_SOURCES:
        return False
    return timezone.localdate(line.created_at) > line.accounting_date


def entry_data(line: CostLine) -> WorkshopEntryData:
    """Shape one CostLine as a workshop timesheet entry."""
    job = line.cost_set.job
    meta = line.meta
    # Opus: The canonical readers, not a defaulted `meta.get`. Both keys are
    # denormalised onto the line at write time, so a default here could only mask
    # bad data — and this module already imports `hour_categories` for
    # `scheduled_hours`, so it was using two-thirds of a shared vocabulary and
    # its own copy of the rest (ADR 0015, ADR 0039).
    wage_multiplier = hour_categories.wage_rate_multiplier(line)
    is_billable = hour_categories.is_billable(line)
    default_bill = wage_multiplier if is_billable else ZERO_MULTIPLIER
    bill_multiplier = _meta_multiplier(meta, "bill_rate_multiplier", default_bill)
    return {
        "id": str(line.id),
        "job_id": str(job.id),
        "job_number": job.job_number,
        "job_name": job.name,
        "company_name": job.company.name if job.company else "",
        "description": line.desc or "",
        "hours": float(line.quantity),
        "accounting_date": line.accounting_date,
        "start_time": _meta_time(meta, "start_time"),
        "end_time": _meta_time(meta, "end_time"),
        "is_billable": is_billable,
        "wage_rate_multiplier": float(wage_multiplier),
        "bill_rate_multiplier": float(bill_multiplier),
        "approved": line.approved,
        "entered_late": entered_late(line),
        "remote_entry": line.remote_entry,
        "created_at": line.created_at,
        "updated_at": line.updated_at,
    }


def _summary(entries: list[CostLine]) -> WorkshopSummaryData:
    """Totals for a staff member's day."""
    # Opus: The shared split, not a second sum with its own billable rule. This
    # decided billability with a defaulted `meta.get` while every other screen
    # asked `hour_categories` — the shape v1's divergent totals started as.
    categories = hour_categories.categorise(entries)
    total_hours = categories.total
    billable_hours = categories.billable
    return {
        "total_hours": float(total_hours),
        "billable_hours": float(billable_hours),
        "non_billable_hours": float(total_hours - billable_hours),
    }


def day_time_lines(staff: Staff, entry_date: date) -> list[CostLine]:
    """Return the staff member's time lines for one date, in entry order.

    Shared by the self-service projection (``list_entries``) and the
    management projection (``management_day_data``). Both projections read
    only local columns, FK ids and the job via ``cost_set__job__company`` —
    no other related legs are joined because nothing dereferences them.
    """
    return list(
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            staff=staff,
            accounting_date=entry_date,
        ).select_related("cost_set__job__company", "xero_pay_item")
    )


def _week_hours(staff: Staff, entry_date: date) -> WorkshopWeekData:
    """Approved and waiting hours for the payroll week the date falls in.

    The same week and the same lines the weekly payroll screen reports as held
    back, so the worker's "waiting" and the office's figure are one number.
    """
    week_start = payroll_week_start(entry_date)
    # Lunch is logged, not hours.
    totals = (
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            staff=staff,
            accounting_date__gte=week_start,
            accounting_date__lte=week_start + timedelta(days=PAYROLL_WEEK_DAYS - 1),
        )
        .exclude(UNPAID_TIME)
        .aggregate(
            approved_hours=Coalesce(Sum("quantity", filter=Q(approved=True)), Decimal("0")),
            waiting_hours=Coalesce(Sum("quantity", filter=Q(approved=False)), Decimal("0")),
        )
    )
    return {
        "approved_hours": float(totals["approved_hours"]),
        "waiting_hours": float(totals["waiting_hours"]),
    }


def list_entries(staff: Staff, entry_date: date) -> WorkshopDayData:
    """List one person's entries for a date, with the day's summary.

    His breaks travel in ``breaks`` and not in ``entries``: nothing that reads
    the day's jobs (the last job used, the count of jobs, the job blocks) then
    has to know which job a break is booked to. His paid breaks are hours and
    in every total; lunch is logged, not hours, and in none.
    """
    lines = day_time_lines(staff, entry_date)
    entries, break_lines = attendance.split_breaks(lines)
    row = AttendanceDay.objects.filter(staff=staff, date=entry_date).first()
    breaks = attendance.day_breaks(entry_date, row, break_lines)
    standard = attendance.standard_day(entry_date)
    today = timezone.localdate()
    return {
        "date": entry_date,
        "entries": [entry_data(line) for line in entries],
        "summary": _summary(lines),
        "week": _week_hours(staff, entry_date),
        "day": attendance.attendance_data(row),
        "breaks": breaks,
        "fill": attendance.fill_figures(
            row, sum((line.quantity for line in entries), Decimal(0)), break_lines
        ),
        "standard": None if standard is None else {"start": standard.start, "end": standard.end},
        "missed_clock_out_finish": attendance.missed_clock_out_finish(row, today),
        "default_entry_start": default_entry_start(entry_date, row, entries, break_lines),
        "calendar": attendance.calendar_bounds(
            row,
            standard,
            [span for line in entries if (span := timed_span(line))]
            + [(each["start"], each["end"]) for each in breaks],
        ),
        "pending": attendance.pending_day(staff, today),
    }


def default_entry_start(
    day: date, row: AttendanceDay | None, entries: list[CostLine], break_lines: list[CostLine]
) -> time:
    """Return where his next entry starts: after his latest, else when he clocked in.

    Failing both, the standard start. A start that lands inside a break moves
    to the end of it, since breaks are outside job time. General work is the
    rest of the day, not an entry: what he enters goes into it (owner,
    2026-10-26), so an entry starts where his own entries end.
    """
    finishes = [
        span[1] for line in entries if not is_general_work_fill(line) and (span := timed_span(line))
    ]
    if finishes:
        start = max(finishes)
    elif row is not None:
        start = row.clock_in
    else:
        start = attendance.standard_entry_start(day)
    return attendance.start_after_breaks(start, attendance.break_windows(day, row, break_lines))


def next_entry_start(owner: Staff, day: date) -> time:
    """Return where an entry he saves without times will start on the day."""
    row = AttendanceDay.objects.filter(staff=owner, date=day).first()
    entries, break_lines = attendance.split_breaks(day_time_lines(owner, day))
    return default_entry_start(day, row, entries, break_lines)


def day_break_windows(staff: Staff, day: date) -> list[attendance.Window]:
    """Return the day's breaks as the stretches an entry is placed around."""
    row = AttendanceDay.objects.filter(staff=staff, date=day).first()
    _, break_lines = attendance.split_breaks(day_time_lines(staff, day))
    return attendance.break_windows(day, row, break_lines)


def timed_span(line: CostLine) -> tuple[time, time] | None:
    """Return the entry's start and end when it has both, else None."""
    start = _meta_time(line.meta, "start_time")
    end = _meta_time(line.meta, "end_time")
    if start is None or end is None:
        return None
    return start, end


def timed_window(line: CostLine) -> attendance.Window | None:
    """Return the stretch of the day the entry holds, when it has both times."""
    span = timed_span(line)
    return None if span is None else attendance.Window(*span)


class ManagementStaffData(TypedDict):
    """Data contract for ManagementStaffData."""

    id: str
    name: str
    first_name: str
    last_name: str


class ManagementSummaryData(WorkshopSummaryData):
    """Data contract for ManagementSummaryData."""

    entry_count: int
    scheduled_hours: float
    # Money stays on the superuser's screen: the self-service summary, which a
    # worker's phone and the office's Approve time read, carries none.
    total_cost: float
    total_revenue: float


class TimesheetCostLineData(CostLineData):
    """A cost line plus its job identity, for the management entry grid."""

    job_id: UUID
    job_number: int
    job_name: str
    company_name: str | None


class ManagementDayData(TypedDict):
    """Data contract for ManagementDayData."""

    cost_lines: list[TimesheetCostLineData]
    staff: ManagementStaffData
    date: date
    summary: ManagementSummaryData


def _timesheet_line_data(line: CostLine) -> TimesheetCostLineData:
    """One implementation of "CostLine → wire dict" (job_service) plus the job overlay."""
    job = line.cost_set.job
    return {
        **cost_line_data(line),
        "job_id": job.id,
        "job_number": job.job_number,
        "job_name": job.name,
        "company_name": job.company.name if job.company else None,
    }


def management_day_data(staff: Staff, entry_date: date) -> ManagementDayData:
    """Any staff member's day for the management entry screen.

    Lines go out CostLine-shaped (the entry grid patches them through the
    cost-line endpoints, so it needs the full line, not the self-service
    entry projection).
    """
    lines = day_time_lines(staff, entry_date)
    base = _summary(lines)
    return {
        "cost_lines": [_timesheet_line_data(line) for line in lines],
        "staff": {
            "id": str(staff.id),
            "name": staff.get_display_name(),
            "first_name": staff.first_name,
            "last_name": staff.last_name,
        },
        "date": entry_date,
        "summary": {
            **base,
            "entry_count": len(lines),
            "scheduled_hours": float(
                hour_categories.scheduled_hours(staff, entry_date, weekend_enabled=True)
            ),
            "total_cost": float(sum((line.total_cost for line in lines), Decimal("0"))),
            "total_revenue": float(sum((line.total_rev for line in lines), Decimal("0"))),
        },
    }


def pricing_meta(
    *,
    staff: Staff,
    accounting_date: date,
    wage_rate_multiplier: Decimal,
    bill_rate_multiplier: Decimal | None,
    is_billable: bool,
) -> dict[str, object]:
    """Build the meta a time line carries into the rate pipeline."""
    meta: dict[str, object] = {
        "staff_id": str(staff.id),
        "date": accounting_date.isoformat(),
        "is_billable": is_billable,
        "wage_rate_multiplier": float(wage_rate_multiplier),
        "created_from_timesheet": True,
    }
    if bill_rate_multiplier is not None:
        meta["bill_rate_multiplier"] = float(bill_rate_multiplier)
    return meta


class _Placement(TypedDict, total=False):
    start_time: time
    end_time: time


def _placed(owner: Staff, day: date, hours: Decimal) -> _Placement:
    """Place hours given without times after his latest entry, stepping over the breaks.

    Hours are all he has to say; the times are the picture that lets the day
    draw. Hours that would run past midnight from there keep no picture: the
    entry is saved without times, as it always could be, rather than refused
    or drawn shorter than the hours it holds.
    """
    start = next_entry_start(owner, day)
    finish = attendance.finish_in_the_day(start, hours, day_break_windows(owner, day))
    if finish is None:
        return {}
    return {"start_time": start, "end_time": finish}


def create_entry(
    actor: Staff,
    owner: Staff,
    data: WorkshopEntryCreateData,
    location: EntryLocation | None = None,
    *,
    source: str | None = None,
) -> WorkshopEntryData:
    """Create a time line for ``owner``, saved by ``actor``.

    The two are the same person when someone books their own time. The owner's
    wage prices the line; who saved it decides whether it starts approved and
    whether it is marked as saved away from the workshop. ``location`` is
    where the actor's phone says it is; None when it gave none.

    ``source`` marks a line nobody typed (the breaks put on a day when it is
    closed, the sweep's General work): never marked late or remote, since
    there was no entry to judge.
    """
    job = Job.objects.select_related("company", "default_xero_pay_item").get(id=data["job_id"])

    with transaction.atomic():
        # His day is read and placed on under a lock on him, so two entries
        # saved at once are placed one after the other, not on one slot.
        Staff.objects.select_for_update().filter(pk=owner.pk).first()
        if data.get("start_time") is None and data.get("end_time") is None:
            data = {**data, **_placed(owner, data["accounting_date"], data["hours"])}
        _validate_time_consistency(
            data["accounting_date"], data.get("start_time"), data.get("end_time"), data["hours"]
        )
        lock_costing_jobs(_with_general_work({job.id}))
        _refuse_outside_employment(owner, data["accounting_date"])
        is_break = job.id == attendance.break_job_id()
        if not is_break:
            _refuse_all_inside_a_break(owner, data)
        overtime = overtime_part(
            owner,
            data["accounting_date"],
            data["hours"],
            wage_rate_multiplier=data.get("wage_rate_multiplier", ORDINARY),
            job_id=job.id,
        )
        if (
            job.is_urgent
            and data.get("bill_rate_multiplier") is None
            and data.get("is_billable", True)
        ):
            # An urgent job is charged at time and a half whoever books it
            # (owner): the default the office grid offers, here for everyone.
            data = {**data, "bill_rate_multiplier": URGENT_CHARGE}
        if overtime == 0:
            line = _save_entry(actor, owner, job, data, location, source=source)
        elif overtime == data["hours"]:
            line = _save_entry(actor, owner, job, _at_overtime(data), location, source=source)
        else:
            ordinary, late = _split_at_overtime(owner, data, overtime)
            line = _save_entry(actor, owner, job, ordinary, location, source=source)
            _save_entry(actor, owner, job, late, location, source=source)
        if source != SWEPT_GENERAL_WORK:
            refill_general_work(owner, data["accounting_date"], actor)
    return entry_data(line)


def _with_general_work(job_ids: set[UUID]) -> set[UUID]:
    """Return the jobs a write to a day locks: its own and the General work it may rebuild.

    Taken in one id-ordered step, as the sweep takes them: one after the
    other, a sweep holding General work and waiting for this entry's job
    would deadlock with it.
    """
    general_work_id = CompanyDefaults.get_solo().general_work_job_id
    return job_ids if general_work_id is None else job_ids | {general_work_id}


def is_general_work_fill(line: CostLine) -> bool:
    """Whether the line is the General work filling the rest of a day, not an entry.

    A fill line the office moved to a job is time on that job, billed to its
    customer, and stays when the day's General work is made again.
    """
    source: object = line.meta.get("source")
    return (
        source == SWEPT_GENERAL_WORK
        and line.cost_set.job_id == CompanyDefaults.get_solo().general_work_job_id
    )


def refill_general_work(owner: Staff, day: date, actor: Staff) -> Decimal:
    """Make a filled day's General work the time on no job and no break; return the hours made.

    General work is "like a bit flag" (owner, 2026-10-26): on a day filled
    with it, "any time that isn't on a job or break is general work". The flag
    is the day's; these lines are its picture for every reader of time lines.
    When the gaps change the lines are made again, last, so the hours past the
    usual day are the General work's and the new lines wait for approval, as
    any change does. When the gaps are as they were nothing is touched, so an
    edit elsewhere takes no approval off. Called inside the write's
    transaction, under his lock.
    """
    row = AttendanceDay.objects.filter(staff=owner, date=day).first()
    if row is None or not row.general_work_fill:
        return Decimal(0)
    general_work_id = CompanyDefaults.get_solo().general_work_job_id
    if general_work_id is None:
        raise ValueError(f"{owner} on {day} is filled with General work, but none is set up")
    lines = day_time_lines(owner, day)
    filled = [line for line in lines if is_general_work_fill(line)]
    entries, break_lines = attendance.split_breaks(
        [line for line in lines if not is_general_work_fill(line)]
    )
    # Still clocked in: the day has no end to fill to yet.
    windows = attendance.unallocated_windows(day, row, entries, break_lines) or []
    current = [window for line in filled if (window := timed_window(line)) is not None]
    # Compared as joined stretches: the overtime split cuts one gap into two
    # lines. Their own minutes must add up to the joined ones too, or two
    # lines over one stretch would stand and pay it twice.
    joined = attendance.merged_minutes(current)
    if (
        len(current) == len(filled)
        and joined == attendance.merged_minutes(windows)
        and sum(end - start for start, end in joined)
        == sum(end - start for each in current for start, end in attendance.merged_minutes([each]))
    ):
        return Decimal(0)
    lock_costing_jobs([general_work_id])
    for line in filled:
        _delete_line(actor, line, None)
    for window in windows:
        create_entry(
            actor,
            owner,
            {
                "job_id": general_work_id,
                "accounting_date": day,
                "hours": attendance.hours_for(window.start, window.end, []),
                "start_time": window.start,
                "end_time": window.end,
                # A shop job's time is billed to nobody; the model refuses otherwise.
                "is_billable": False,
            },
            source=SWEPT_GENERAL_WORK,
        )
    return sum((attendance.hours_for(each.start, each.end, []) for each in windows), Decimal(0))


def fill_with_general_work(owner: Staff, day: date, actor: Staff) -> Decimal:
    """Put the rest of his day on General work from now on; return the hours it made.

    Entering, not approving: anyone fills their own day ("I can't be bothered
    to enter the rest"), the office anyone's (owner, 2026-10-26). The rest of
    a day runs to its clock-out, so a day needs both clock times first.
    """
    if actor.id != owner.id and not actor.is_office_staff:
        raise AccessDeniedError(gettext("Only office staff fill another person's day."))
    # His lock first, as every write to his day takes it.
    Staff.objects.select_for_update().filter(pk=owner.pk).first()
    row = AttendanceDay.objects.select_for_update().filter(staff=owner, date=day).first()
    if row is None or row.clock_out is None:
        raise ConflictError(
            gettext("Set the day's clock times before putting the rest of it on General work.")
        )
    if not row.general_work_fill:
        row.general_work_fill = True
        row.save(update_fields=["general_work_fill", "updated_at"])
        record_day_event(
            staff=actor,
            worker=owner,
            day=day,
            event_type="general_work_on",
            before=None,
            after=None,
            trusted=not saved_remotely(actor, None),
        )
    return refill_general_work(owner, day, actor)


def _refuse_outside_employment(owner: Staff, day: date) -> None:
    """Refuse time on a day he was not employed: before he started, or after he left."""
    if owner.is_active_on(day):
        return
    if day < owner.employment_start_date:
        raise InvalidInputError(
            gettext("%(name)s starts on %(date)s, so time before it can't be entered.")
            % {"name": owner.get_display_full_name(), "date": owner.employment_start_date}
        )
    if owner.date_left is None:
        raise ValueError(f"{owner.id} is not employed on {day} yet has no leaving date")
    raise InvalidInputError(
        gettext("%(name)s's last day was %(date)s, so time after it can't be entered.")
        % {
            "name": owner.get_display_full_name(),
            "date": owner.date_left - timedelta(days=1),
        }
    )


def _refuse_all_inside_a_break(owner: Staff, data: WorkshopEntryCreateData) -> None:
    """Refuse an entry that sits wholly inside one of his breaks: it holds no work.

    He was on the break, or he worked through it and the break should go;
    the refusal says which, rather than saving an entry of nothing.
    """
    start, end = data.get("start_time"), data.get("end_time")
    if start is None or end is None:
        return
    day = data["accounting_date"]
    row = AttendanceDay.objects.filter(staff=owner, date=day).first()
    _, break_lines = attendance.split_breaks(day_time_lines(owner, day))
    for each in attendance.day_breaks(day, row, break_lines):
        if each["start"] <= start and end <= each["end"]:
            name = each["name"].lower()
            raise InvalidInputError(
                gettext(
                    "That is all inside your %(name)s. If you worked through it, "
                    "delete the %(name)s."
                )
                % {"name": name}
            )


#: The rate time is at unless he chose another, and the rate the hours past his
#: usual day default to (owner, 2026-10-24).
ORDINARY = Decimal("1.0")
OVERTIME = Decimal("1.5")
#: What an urgent job is charged at by default, as the office grid offers it.
URGENT_CHARGE = Decimal("1.5")
#: The smallest piece an entry is split into at the overtime point: below it,
#: the whole entry takes the rate of its larger part.
_SMALLEST_SPLIT = Decimal("0.25")


def overtime_part(
    owner: Staff,
    day: date,
    hours: Decimal,
    *,
    wage_rate_multiplier: Decimal,
    job_id: UUID | None,
) -> Decimal:
    """Return how many of a new entry's hours default to time and a half.

    ``job_id`` is None when the job is not chosen yet: the answer is then
    for ordinary work.

    Only an entry at ordinary time takes the default: a rate someone chose
    stands, and a break is never overtime. On a public holiday every hour
    is time and a half; otherwise the hours past his usual day are. A piece
    under a quarter hour is not split off: the entry goes whole to the rate
    of its larger part.
    """
    if wage_rate_multiplier != ORDINARY or (
        job_id is not None and (job_id == attendance.break_job_id() or job_id in leave_job_ids())
    ):
        return Decimal(0)
    overtime = overtime_hours(
        owner,
        day,
        hours,
        general_work_counts=job_id == CompanyDefaults.get_solo().general_work_job_id,
    )
    return split_off(hours, overtime)


def split_off(hours: Decimal, overtime: Decimal) -> Decimal:
    """Return how many of ``hours`` go at overtime once a split under a quarter hour is undone.

    A piece under a quarter hour is not split off: the whole goes to the rate
    of its larger part.
    """
    ordinary = hours - overtime
    if 0 < min(overtime, ordinary) < _SMALLEST_SPLIT:
        return hours if overtime > ordinary else Decimal(0)
    return overtime


def on_a_public_holiday(owner: Staff, day: date) -> bool:
    """Whether the day is a public holiday for him: the office closure gave him its holiday."""
    holiday_job = (
        LeaveType.objects.filter(code=LeaveType.Code.PUBLIC_HOLIDAY)
        .values_list("job_id", flat=True)
        .first()
    )
    if holiday_job is None:
        # No public-holiday leave set up: no closure has given anyone a holiday.
        return False
    return CostLine.objects.filter(
        kind="time",
        staff=owner,
        accounting_date=day,
        managed_by=CostLineOwner.LEAVE,
        cost_set__job_id=holiday_job,
    ).exists()


def _charge_urgent_at_least(job: Job, meta: dict[str, object]) -> None:
    """Re-derive a dropped charge as on create: an urgent job's at time and a half at least.

    The higher of the two applies, never both (owner): a charge someone set stands.
    """
    if not job.is_urgent or "bill_rate_multiplier" in meta or not meta["is_billable"]:
        return
    wage = Decimal(str(meta["wage_rate_multiplier"]))
    meta["bill_rate_multiplier"] = float(max(URGENT_CHARGE, wage))


def _at_overtime(data: WorkshopEntryCreateData) -> WorkshopEntryCreateData:
    """Return the entry at time and a half, charged at least that when it is billed at all."""
    late: WorkshopEntryCreateData = {**data, "wage_rate_multiplier": OVERTIME}
    given = data.get("bill_rate_multiplier")
    if given is not None and data.get("is_billable", True):
        # The higher of the two applies, never both (owner): an urgent job's
        # overtime is charged at time and a half, not two and a quarter.
        late["bill_rate_multiplier"] = max(given, OVERTIME)
    return late


def overtime_hours(
    owner: Staff,
    day: date,
    hours: Decimal,
    *,
    already_on_the_day: bool = True,
    general_work_counts: bool = False,
) -> Decimal:
    """Return how many of ``hours``, added to his day, fall past his usual day.

    ``already_on_the_day`` False asks of ``hours`` alone: how many of a day of
    that many hours are past the usual day. The General work filling the day
    is rebuilt after anything he enters, so it counts toward the usual day
    only for the General work itself (``general_work_counts``): the hours past
    the usual day are always the General work's.

    The first hours of a day are ordinary and the rest time and a half
    (owner, 2026-10-25: "the first 8 hours is standard"). The usual day is the
    company's start to stop for the weekday, so a weekend has none. Only time
    on jobs counts: a break or leave is not work.
    """
    standard = attendance.standard_day(day)
    # Salary pays no overtime earnings: its hours allocate a fixed cost.
    if standard is None or owner.pay_basis == "salary":
        return Decimal(0)
    if on_a_public_holiday(owner, day):
        return hours
    usual = attendance.hours_for(standard.start, standard.end, [])
    worked = Decimal(0)
    if already_on_the_day:
        entries, _ = attendance.split_breaks(day_time_lines(owner, day))
        leave = leave_job_ids()
        worked = sum(
            (
                line.quantity
                for line in entries
                if line.cost_set.job_id not in leave
                and (general_work_counts or not is_general_work_fill(line))
            ),
            Decimal(0),
        )
    return min(hours, max(hours - (usual - worked), Decimal(0)))


def _split_at_overtime(
    owner: Staff, data: WorkshopEntryCreateData, overtime: Decimal
) -> tuple[WorkshopEntryCreateData, WorkshopEntryCreateData]:
    """Split an entry where its hours pass his usual day: the ordinary part, then the rest.

    The two rates are two lines, since a line is paid and charged at one. The
    split falls where the ordinary hours end, stepping over his breaks; with
    no times (past midnight) the two keep none.
    """
    ordinary_hours = data["hours"] - overtime
    start, end = data.get("start_time"), data.get("end_time")
    ordinary: WorkshopEntryCreateData = {**data, "hours": ordinary_hours}
    late: WorkshopEntryCreateData = {**_at_overtime(data), "hours": overtime}
    if start is None or end is None:
        return ordinary, late
    breaks = day_break_windows(owner, data["accounting_date"])
    split = attendance.finish_in_the_day(start, ordinary_hours, breaks)
    if split is None:
        raise ValueError(f"Hours ending at {end:%H:%M} split past midnight from {start:%H:%M}")
    ordinary["end_time"] = split
    late["start_time"] = attendance.start_after_breaks(split, breaks)
    return ordinary, late


def _save_entry(  # noqa: PLR0913 -- the entry, whose it is, who saves it, where from and why
    actor: Staff,
    owner: Staff,
    job: Job,
    data: WorkshopEntryCreateData,
    location: EntryLocation | None,
    *,
    source: str | None,
) -> CostLine:
    """Price and save one time line, recording who made it."""
    wage_rate_multiplier = data.get("wage_rate_multiplier", ORDINARY)
    cost_set = get_or_create_cost_set(job, "actual")
    meta = pricing_meta(
        staff=owner,
        accounting_date=data["accounting_date"],
        wage_rate_multiplier=wage_rate_multiplier,
        bill_rate_multiplier=data.get("bill_rate_multiplier"),
        is_billable=data.get("is_billable", True),
    )
    if source is not None:
        meta["source"] = source
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if start_time is not None:
        meta["start_time"] = _format_time(start_time)
    if end_time is not None:
        meta["end_time"] = _format_time(end_time)

    subtype_id = data.get("labour_subtype_id")
    pricing = price_time_entry(
        job=job,
        staff=owner,
        meta=meta,
        labour_subtype=None if subtype_id is None else LabourSubtype.objects.get(id=subtype_id),
    )
    meta.update(pricing.meta_updates())

    line = CostLine(
        cost_set=cost_set,
        kind="time",
        desc=data.get("description") or None,
        quantity=data["hours"],
        unit_cost=pricing.unit_cost,
        unit_rev=pricing.unit_rev,
        accounting_date=data["accounting_date"],
        staff=owner,
        xero_pay_item_id=pricing.pay_item_id,
        labour_subtype=pricing.labour_subtype,
        ext_refs={},
        meta=meta,
        # Waiting, whoever enters it: entering and approving are two
        # operations, even by one person (owner, 2026-10-26).
        approved=False,
        remote_entry=source is None and saved_remotely(actor, location),
    )
    line.save()
    update_latest_actual(job, cost_set.rev, cost_set.id, actor)
    record_timesheet_event(
        staff=actor,
        event_type="entry_created",
        line=line,
        before=None,
        trusted=not line.remote_entry,
    )
    return line


def _editable_line(actor: Staff, entry_id: UUID) -> CostLine:
    """Fetch a time line the actor may edit: their own, or anyone's for the office."""
    line = CostLine.objects.select_related(
        "cost_set__job__company",
        "cost_set__job__default_xero_pay_item",
        "labour_subtype",
        "xero_pay_item",
        "staff",
    ).get(id=entry_id, kind="time")
    _refuse_another_persons_entry(
        line, actor, gettext("You can only update your own timesheet entries.")
    )
    refuse_workflow_managed(line, "edit")
    return line


def _apply_billing_changes(
    line: CostLine, meta: dict[str, object], data: WorkshopEntryUpdateData
) -> bool:
    """Fold the pricing patch fields into the line and ``meta``; report whether to reprice.

    Drop the stored ``bill_rate_multiplier`` when ``is_billable`` flips back to
    true so the rate pipeline re-derives it from the wage multiplier rather
    than leaving the line at zero.
    """
    reprice = False
    if "labour_subtype_id" in data:
        line.labour_subtype = LabourSubtype.objects.get(id=data["labour_subtype_id"])
        reprice = True
    if "is_billable" in data:
        meta["is_billable"] = data["is_billable"]
        if data["is_billable"]:
            meta.pop("bill_rate_multiplier", None)
        else:
            meta["bill_rate_multiplier"] = 0.0
        reprice = True
    if "wage_rate_multiplier" in data:
        meta["wage_rate_multiplier"] = float(data["wage_rate_multiplier"])
        if "bill_rate_multiplier" not in data:
            meta.pop("bill_rate_multiplier", None)
        reprice = True
    if "bill_rate_multiplier" in data:
        bill_multiplier = normalize_multiplier(data["bill_rate_multiplier"])
        meta["bill_rate_multiplier"] = float(bill_multiplier)
        meta["is_billable"] = bill_multiplier > ZERO_MULTIPLIER
        reprice = True
    return reprice


def _apply_scalar_changes(
    line: CostLine, meta: dict[str, object], data: WorkshopEntryUpdateData
) -> bool:
    """Fold the non-pricing patch fields onto the line; report whether anything changed."""
    changed = False
    if "description" in data:
        line.desc = data["description"] or None
        changed = True
    if "hours" in data:
        line.quantity = data["hours"]
        changed = True
    if "accounting_date" in data:
        line.accounting_date = data["accounting_date"]
        meta["date"] = data["accounting_date"].isoformat()
        changed = True
    if "start_time" in data:
        meta["start_time"] = _format_time(data["start_time"])
        changed = True
    if "end_time" in data:
        meta["end_time"] = _format_time(data["end_time"])
        changed = True
    return changed


_MOVES_THE_FINISH = frozenset({"hours", "start_time", "accounting_date"})


def _redraw_finish(line: CostLine, meta: dict[str, object], data: WorkshopEntryUpdateData) -> None:
    """Redraw an edited entry's finish from its hours, unless a finish was given.

    Hours are the truth and the times their picture: new hours, a new start or
    a new day redraw the finish rather than being refused by it. Past midnight
    from the start, the hours stand and keep no picture.
    """
    start = _meta_time(meta, "start_time")
    if start is None or "end_time" in data or not data.keys() & _MOVES_THE_FINISH:
        return
    windows = day_break_windows(_owner_of(line), line.accounting_date)
    finish = attendance.finish_in_the_day(start, line.quantity, windows)
    if finish is None:
        meta["start_time"] = None
        meta["end_time"] = None
    else:
        meta["end_time"] = _format_time(finish)


def update_entry(
    actor: Staff, data: WorkshopEntryUpdateData, location: EntryLocation | None = None
) -> WorkshopEntryData:
    """Update an entry: the actor's own, or anyone's when the actor is office staff.

    The entry stays its owner's and is priced at the owner's wage. ``location``
    is where the actor's phone says it is; None when it gave none.
    """
    line = _editable_line(actor, data["entry_id"])

    with transaction.atomic():
        # His lock before the jobs', as every write to his day takes them.
        Staff.objects.select_for_update().filter(pk=_owner_of(line).pk).first()
        job_ids = {line.cost_set.job_id}
        if "job_id" in data:
            job_ids.add(data["job_id"])
        lock_costing_jobs(_with_general_work(job_ids))
        line = _editable_line(actor, data["entry_id"])
        if line.cost_set.job_id not in job_ids:
            raise ConflictError(
                gettext("This entry moved to another job. Reload before editing it.")
            )
        if is_general_work_fill(line) and {"start_time", "end_time", "hours"} & data.keys():
            raise InvalidInputError(
                gettext(
                    "General work fills the time not on a job or a break. "
                    "Change the entries or breaks around it."
                )
            )
        before = snapshot_if_entry(line)
        day_before = line.accounting_date
        a_change_takes_the_approval_off(line)
        meta = dict(line.meta)
        changed = _apply_scalar_changes(line, meta, data)
        reprice = _apply_billing_changes(line, meta, data)

        job = line.cost_set.job
        moved_cost_set = None
        if "job_id" in data and data["job_id"] != job.id:
            job = Job.objects.select_related("company", "default_xero_pay_item").get(
                id=data["job_id"]
            )
            moved_cost_set = move_time_line(
                line,
                job,
                meta,
                billing_explicit="is_billable" in data or "bill_rate_multiplier" in data,
            )
            changed = True
            reprice = True

        if reprice:
            _charge_urgent_at_least(job, meta)
            pricing = price_time_entry(
                job=job, staff=_owner_of(line), meta=meta, labour_subtype=line.labour_subtype
            )
            meta.update(pricing.meta_updates())
            line.unit_cost = pricing.unit_cost
            line.unit_rev = pricing.unit_rev
            line.xero_pay_item_id = pricing.pay_item_id
            line.labour_subtype = pricing.labour_subtype
            changed = True

        if not changed:
            raise ValueError(gettext("No changes supplied."))

        _redraw_finish(line, meta, data)

        # Validated on the merged entry, not the patch alone: a PATCH that moves
        # one time can break agreement with the stored other half.
        _validate_time_consistency(
            line.accounting_date,
            _meta_time(meta, "start_time"),
            _meta_time(meta, "end_time"),
            line.quantity,
        )

        # Changed by someone: no longer the default the finish may take away.
        mark_break_edited(meta)
        line.meta = meta
        # Only ever set here: an edit made at the workshop does not vouch for
        # an entry first made somewhere else.
        remote = saved_remotely(actor, location)
        if remote:
            line.remote_entry = True
        line.save()
        if moved_cost_set is not None:
            update_latest_actual(job, moved_cost_set.rev, moved_cost_set.id, actor)
        record_timesheet_event(
            staff=actor,
            event_type="entry_moved" if moved_cost_set is not None else "entry_updated",
            line=line,
            before=before,
            trusted=not remote,
        )
        owner = _owner_of(line)
        for day in {day_before, line.accounting_date}:
            refill_general_work(owner, day, actor)

    return entry_data(line)


@transaction.atomic
def delete_entry(actor: Staff, entry_id: UUID, location: EntryLocation | None = None) -> None:
    """Delete an entry: the actor's own, or anyone's when the actor is office staff."""
    line = CostLine.objects.get(id=entry_id, kind="time")
    # His lock before the jobs', as every write to his day takes them.
    Staff.objects.select_for_update().filter(pk=_owner_of(line).pk).first()
    job_id = line.cost_set.job_id
    lock_costing_jobs(_with_general_work({job_id}))
    # Locked on the line alone: the snapshot's joins are nullable, which
    # Postgres refuses under FOR UPDATE.
    line = (
        CostLine.objects.select_for_update(of=("self",))
        .select_related("cost_set__job", "labour_subtype", "xero_pay_item")
        .get(pk=line.pk)
    )
    if line.cost_set.job_id != job_id:
        raise ConflictError(gettext("This entry moved to another job. Reload before deleting it."))
    _refuse_another_persons_entry(
        line, actor, gettext("You can only delete your own timesheet entries.")
    )
    refuse_workflow_managed(line, "cancel")
    owner, day = _owner_of(line), line.accounting_date
    if is_general_work_fill(line):
        _general_work_off(owner, day, actor, location)
        return
    _delete_line(actor, line, location)
    refill_general_work(owner, day, actor)


def _delete_line(actor: Staff, line: CostLine, location: EntryLocation | None) -> None:
    """Delete one time line the caller holds locked, recording who did."""
    # Recorded before the delete: Django clears the pk on the instance it
    # deleted, and the event names the line by that id.
    record_timesheet_event(
        staff=actor,
        event_type="entry_deleted",
        line=line,
        before=snapshot_if_entry(line),
        trusted=not saved_remotely(actor, location),
    )
    entry_id = line.id
    line.delete()
    logger.info("Deleted workshop timesheet entry %s by staff %s", entry_id, actor.id)


def _general_work_off(
    owner: Staff, day: date, actor: Staff, location: EntryLocation | None
) -> None:
    """Take the day's General work off, all of it: one line deleted is the fill turned off.

    A refill would put a single deleted line straight back; sweeping the day
    again turns it on.
    """
    AttendanceDay.objects.filter(staff=owner, date=day).update(
        general_work_fill=False, updated_at=timezone.now()
    )
    record_day_event(
        staff=actor,
        worker=owner,
        day=day,
        event_type="general_work_off",
        before=None,
        after=None,
        trusted=not saved_remotely(actor, location),
    )
    for each in day_time_lines(owner, day):
        if is_general_work_fill(each):
            _delete_line(actor, each, location)
