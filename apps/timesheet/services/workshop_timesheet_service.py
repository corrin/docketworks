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
from apps.job.models import Job
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.job.services.job_service import (
    CostLineData,
    cost_line_data,
    get_or_create_cost_set,
    move_time_line,
    refuse_worker_change_to_approved,
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
from apps.timesheet.services.timesheet_events import record_timesheet_event, snapshot_if_entry
from apps.timesheet.services.weekly_timesheet_service import PAYROLL_WEEK_DAYS, payroll_week_start

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
    to the end of it, since breaks are outside job time.
    """
    finishes = [span[1] for line in entries if (span := timed_span(line))]
    if finishes:
        start = max(finishes)
    elif row is not None:
        start = row.clock_in
    else:
        start = attendance.standard_entry_start(day)
    return attendance.start_after_breaks(start, attendance.break_windows(day, row, break_lines))


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


class TimesDisagreeError(InvalidInputError):
    """A finish was given that the hours, laid around the breaks, do not reach."""


def entry_stretches(
    owner: Staff, day: date, job_id: UUID, start: time, hours: Decimal
) -> list[attendance.Window] | None:
    """Return where ``hours`` begun at ``start`` sit in his day, split around his breaks.

    A break is itself one stretch: it is the time the others step around.
    None when the hours would run past midnight.
    """
    if job_id == attendance.break_job_id():
        return attendance.lay_out(start, hours, [])
    return attendance.lay_out(start, hours, day_break_windows(owner, day))


def _refuse_other_finish(start: time, hours: Decimal, finish: time, reached: time | None) -> None:
    if finish <= start:
        raise TimesDisagreeError(gettext("The finish time must be after the start time."))
    if reached != finish:
        raise TimesDisagreeError(
            gettext("%(hours)s hours from %(start)s, around the breaks, do not end at %(finish)s.")
            % {"hours": hours, "start": f"{start:%H:%M}", "finish": f"{finish:%H:%M}"}
        )


def _set_times(meta: dict[str, object], stretch: attendance.Window | None) -> None:
    meta["start_time"] = None if stretch is None else _format_time(stretch.start)
    meta["end_time"] = None if stretch is None else _format_time(stretch.end)


def add_stretches(
    actor: Staff, line: CostLine, stretches: list[attendance.Window], hours: list[Decimal]
) -> list[CostLine]:
    """Save the rest of an entry's stretches as entries of their own, beside ``line``.

    Each is the same booking as ``line`` (job, rates, pay item, approval) for
    its own times, and is dated as made when ``line`` was: splitting an entry
    is no reason to call any of it entered late.
    """
    pieces: list[CostLine] = []
    for stretch, piece_hours in zip(stretches, hours, strict=True):
        meta = dict(line.meta)
        _set_times(meta, stretch)
        piece = CostLine(
            cost_set=line.cost_set,
            kind=line.kind,
            desc=line.desc,
            quantity=piece_hours,
            unit_cost=line.unit_cost,
            unit_rev=line.unit_rev,
            accounting_date=line.accounting_date,
            staff=line.staff,
            xero_pay_item_id=line.xero_pay_item_id,
            labour_subtype=line.labour_subtype,
            ext_refs={},
            meta=meta,
            approved=line.approved,
            remote_entry=line.remote_entry,
        )
        piece.save()
        # created_at is auto_now_add, so the save stamped it now. A microsecond
        # after the entry it came from: the day lists in the order entries were
        # made, so the piece follows it, and it is no later a day than it.
        piece.created_at = line.created_at + timedelta(microseconds=len(pieces) + 1)
        CostLine.objects.filter(pk=piece.pk).update(created_at=piece.created_at)
        record_timesheet_event(
            staff=actor,
            event_type="entry_created",
            line=piece,
            before=None,
            trusted=not piece.remote_entry,
        )
        pieces.append(piece)
    return pieces


def create_entry(
    actor: Staff,
    owner: Staff,
    data: WorkshopEntryCreateData,
    location: EntryLocation | None = None,
    *,
    source: str | None = None,
) -> list[WorkshopEntryData]:
    """Create ``owner``'s time, saved by ``actor``: one entry per stretch around his breaks.

    The two are the same person when someone books their own time. The owner's
    wage prices the lines; who saved them decides whether they start approved
    and whether they are marked as saved away from the workshop. ``location``
    is where the actor's phone says it is; None when it gave none.

    Hours given without times start where his day has got to. A finish given
    with a start must be where the hours, laid around his breaks, end. Hours
    that would run past midnight keep no times.

    ``source`` marks a line nobody typed (the breaks put on a day when it is
    closed, the sweep's General work): never marked late or remote, since
    there was no entry to judge.
    """
    job = Job.objects.select_related("company", "default_xero_pay_item").get(id=data["job_id"])
    wage_rate_multiplier = data.get("wage_rate_multiplier", Decimal("1.0"))
    day, hours = data["accounting_date"], data["hours"]

    with transaction.atomic():
        # His day is read and placed on under a lock on him, so two entries
        # saved at once are placed one after the other, not on one slot.
        Staff.objects.select_for_update().filter(pk=owner.pk).first()
        start, finish = data.get("start_time"), data.get("end_time")
        if start is None and finish is None:
            row = AttendanceDay.objects.filter(staff=owner, date=day).first()
            entries, break_lines = attendance.split_breaks(day_time_lines(owner, day))
            start = default_entry_start(day, row, entries, break_lines)
        stretches = None if start is None else entry_stretches(owner, day, job.id, start, hours)
        if start is not None and finish is not None:
            _refuse_other_finish(
                start, hours, finish, None if stretches is None else stretches[-1].end
            )
        lock_costing_jobs([job.id])
        cost_set = get_or_create_cost_set(job, "actual")
        meta = pricing_meta(
            staff=owner,
            accounting_date=day,
            wage_rate_multiplier=wage_rate_multiplier,
            bill_rate_multiplier=data.get("bill_rate_multiplier"),
            is_billable=data.get("is_billable", True),
        )
        if source is not None:
            meta["source"] = source
        if stretches is None:
            # No picture past midnight; a lone time given is kept as given.
            if data.get("start_time") is not None:
                meta["start_time"] = _format_time(data["start_time"])
            if finish is not None:
                meta["end_time"] = _format_time(finish)
            shares = [hours]
        else:
            _set_times(meta, stretches[0])
            shares = attendance.stretch_hours(stretches, hours)

        pricing = price_time_entry(job=job, staff=owner, meta=meta)
        meta.update(pricing.meta_updates())

        line = CostLine(
            cost_set=cost_set,
            kind="time",
            desc=data.get("description") or None,
            quantity=shares[0],
            unit_cost=pricing.unit_cost,
            unit_rev=pricing.unit_rev,
            accounting_date=day,
            staff=owner,
            xero_pay_item_id=pricing.pay_item_id,
            labour_subtype=pricing.labour_subtype,
            ext_refs={},
            meta=meta,
            # Time the office enters is approved as it is saved, whoever it is
            # for; a worker's own waits for the office.
            approved=actor.is_office_staff,
            remote_entry=source is None and saved_remotely(actor, location),
        )
        line.save()
        record_timesheet_event(
            staff=actor,
            event_type="entry_created",
            line=line,
            before=None,
            trusted=not line.remote_entry,
        )
        pieces = [line]
        if stretches is not None:
            pieces += add_stretches(actor, line, stretches[1:], shares[1:])
        update_latest_actual(job, cost_set.rev, cost_set.id, actor)

    return [entry_data(piece) for piece in pieces]


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


def _apply_billing_changes(meta: dict[str, object], data: WorkshopEntryUpdateData) -> bool:
    """Fold billing-related patch fields into ``meta``; report whether to reprice.

    Drop the stored ``bill_rate_multiplier`` when ``is_billable`` flips back to
    true so the rate pipeline re-derives it from the wage multiplier rather
    than leaving the line at zero.
    """
    reprice = False
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


_MOVES_THE_FINISH = frozenset({"hours", "start_time", "end_time", "accounting_date"})


def _relaid(
    line: CostLine, meta: dict[str, object], data: WorkshopEntryUpdateData, job_id: UUID
) -> tuple[list[attendance.Window], list[Decimal]]:
    """Lay an edited entry out again from its start; return the stretches it no longer holds.

    New hours, a new start or a new day move where the work sits, so the
    entry is laid around his breaks again: the line keeps the first stretch
    and the rest are returned, with their hours, to be saved beside it. A
    finish given must be where that lay-out ends. Past midnight from the
    start, the hours stand and keep no times.
    """
    if not data.keys() & _MOVES_THE_FINISH or ("end_time" in data and data["end_time"] is None):
        return [], []
    return lay_out_again(line, meta, job_id, data.get("end_time"))


def lay_out_again(
    line: CostLine, meta: dict[str, object], job_id: UUID, finish: time | None = None
) -> tuple[list[attendance.Window], list[Decimal]]:
    """Lay a timed line out from its start for its hours; return the stretches beyond the first.

    The line takes the first stretch in ``meta`` and its hours; the rest are
    for ``add_stretches``. A ``finish`` given must be where the lay-out ends.
    Past midnight the hours keep no times. An untimed line is left as it is.
    """
    start = _meta_time(meta, "start_time")
    if start is None:
        return [], []
    stretches = entry_stretches(_owner_of(line), line.accounting_date, job_id, start, line.quantity)
    if finish is not None:
        _refuse_other_finish(
            start, line.quantity, finish, None if stretches is None else stretches[-1].end
        )
    if stretches is None:
        _set_times(meta, None)
        return [], []
    shares = attendance.stretch_hours(stretches, line.quantity)
    _set_times(meta, stretches[0])
    line.quantity = shares[0]
    return stretches[1:], shares[1:]


def update_entry(
    actor: Staff, data: WorkshopEntryUpdateData, location: EntryLocation | None = None
) -> list[WorkshopEntryData]:
    """Update an entry: the actor's own, or anyone's when the actor is office staff.

    The entry stays its owner's and is priced at the owner's wage. An edit that
    moves where the work sits can split it around his breaks: the entry is the
    first stretch and the rest come back beside it. ``location`` is where the
    actor's phone says it is; None when it gave none.
    """
    line = _editable_line(actor, data["entry_id"])

    with transaction.atomic():
        # His lock before the jobs', as every write to his day takes them.
        Staff.objects.select_for_update().filter(pk=_owner_of(line).pk).first()
        job_ids = {line.cost_set.job_id}
        if "job_id" in data:
            job_ids.add(data["job_id"])
        lock_costing_jobs(job_ids)
        line = _editable_line(actor, data["entry_id"])
        if line.cost_set.job_id not in job_ids:
            raise ConflictError(
                gettext("This entry moved to another job. Reload before editing it.")
            )
        refuse_worker_change_to_approved(line, actor)
        before = snapshot_if_entry(line)
        meta = dict(line.meta)
        changed = _apply_scalar_changes(line, meta, data)
        reprice = _apply_billing_changes(meta, data)

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

        rest, rest_hours = _relaid(line, meta, data, job.id)

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
        pieces = [line, *add_stretches(actor, line, rest, rest_hours)]

    return [entry_data(piece) for piece in pieces]


@transaction.atomic
def delete_entry(actor: Staff, entry_id: UUID, location: EntryLocation | None = None) -> None:
    """Delete an entry: the actor's own, or anyone's when the actor is office staff."""
    line = CostLine.objects.get(id=entry_id, kind="time")
    # His lock before the jobs', as every write to his day takes them.
    Staff.objects.select_for_update().filter(pk=_owner_of(line).pk).first()
    job_id = line.cost_set.job_id
    lock_costing_jobs([job_id])
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
    refuse_worker_change_to_approved(line, actor)
    # Recorded before the delete: Django clears the pk on the instance it
    # deleted, and the event names the line by that id.
    record_timesheet_event(
        staff=actor,
        event_type="entry_deleted",
        line=line,
        before=snapshot_if_entry(line),
        trusted=not saved_remotely(actor, location),
    )
    line.delete()
    logger.info("Deleted workshop timesheet entry %s by staff %s", entry_id, actor.id)


def _timed_window(line: CostLine) -> attendance.Window | None:
    span = timed_span(line)
    return None if span is None else attendance.Window(*span)


def cut_entries_under(
    actor: Staff,
    owner: Staff,
    day: date,
    window: attendance.Window,
    location: EntryLocation | None = None,
) -> None:
    """Take a new break's time out of the entries it lands on (owner, 2026-10-24).

    The break wins: he was on it, not on the job. An entry it lands inside is
    left as the stretches either side of it, holding that much less; one it
    covers goes. Untimed entries have no place in the day to land on.
    """
    entries, _ = attendance.split_breaks(day_time_lines(owner, day))
    for line in entries:
        span = _timed_window(line)
        if span is None or span.end <= window.start or span.start >= window.end:
            continue
        kept = [
            stretch
            for stretch in (
                attendance.Window(span.start, min(span.end, window.start)),
                attendance.Window(max(span.start, window.end), span.end),
            )
            if stretch.end > stretch.start
        ]
        if not kept:
            delete_entry(actor, line.id, location)
            continue
        hours = [attendance.hours_for(stretch.start, stretch.end, []) for stretch in kept]
        update_entry(
            actor,
            {
                "entry_id": line.id,
                "start_time": kept[0].start,
                "end_time": kept[0].end,
                "hours": hours[0],
            },
            location,
        )
        add_stretches(actor, CostLine.objects.get(pk=line.pk), kept[1:], hours[1:])


def _booking(line: CostLine) -> tuple[object, ...]:
    """Return what makes two lines the same booking: everything but where they sit in the day."""
    meta = {key: value for key, value in line.meta.items() if key not in {"start_time", "end_time"}}
    return (
        line.cost_set_id,
        line.desc,
        line.approved,
        line.remote_entry,
        line.xero_pay_item_id,
        line.labour_subtype_id,
        line.unit_cost,
        line.unit_rev,
        sorted(meta.items()),
    )


def merge_entries_across(
    actor: Staff,
    owner: Staff,
    day: date,
    window: attendance.Window,
    location: EntryLocation | None = None,
) -> None:
    """Join the entries either side of a break that has gone (owner, 2026-10-24).

    The reverse of ``cut_entries_under``: two stretches of the same booking
    that meet the gap from either side become one entry again, holding all
    the time between its ends that no remaining break covers. Anything else
    beside the gap is left alone, and the gap stays unbooked.
    """
    entries, _ = attendance.split_breaks(day_time_lines(owner, day))
    spans = [(line, span) for line in entries if (span := _timed_window(line)) is not None]
    before = next(((line, span) for line, span in spans if span.end == window.start), None)
    after = next(((line, span) for line, span in spans if span.start == window.end), None)
    if before is None or after is None or _booking(before[0]) != _booking(after[0]):
        return
    start, end = before[1].start, after[1].end
    hours = attendance.hours_for(start, end, day_break_windows(owner, day))
    delete_entry(actor, after[0].id, location)
    update_entry(actor, {"entry_id": before[0].id, "start_time": start, "hours": hours}, location)
