"""Event writes for the timesheet domain — the one place its audit rows are made.

Every write to a timesheet entry, on the office cost-line path and the
workshop self-service path alike, records one ``TimesheetEvent`` inside the
same transaction as the row write, so an entry change and its evidence
commit or roll back together. The before/after snapshots are the entry as a
reader sees it: job number, hours, rates, multipliers, pay item, approval.
"""

from datetime import date
from decimal import Decimal
from typing import TypedDict

from apps.accounts.models import Staff
from apps.core.audit import FieldChange, json_safe, snapshot_changes
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import rate_from_meta
from apps.timesheet.models import TimesheetEvent


class TimesheetLineSnapshot(TypedDict):
    """One timesheet entry as recorded on an event's ``delta_before``/``delta_after``."""

    job: str
    date: str
    start_time: str | None
    end_time: str | None
    hours: str
    description: str | None
    labour_type: str
    wage_multiplier: float | None
    invoice_multiplier: float | None
    billable: bool | None
    wage_rate: str
    charge_out_rate: str
    pay_item: str | None
    approved: bool


#: The columns' own precisions: an in-flight instance holds the Decimal the
#: request sent ("4.00"), the row holds "4.000", and the snapshot is the row.
HOURS = Decimal("0.001")
MONEY = Decimal("0.01")

#: How each snapshot key reads in ``detail.changes`` and the history panel.
SNAPSHOT_LABELS: dict[str, str] = {
    "job": "Job",
    "date": "Date",
    "start_time": "Start",
    "end_time": "End",
    "hours": "Hours",
    "description": "Description",
    "labour_type": "Labour type",
    "wage_multiplier": "Wage multiplier",
    "invoice_multiplier": "Invoice multiplier",
    "billable": "Billable",
    "wage_rate": "Wage $/h",
    "charge_out_rate": "Charge-out $/h",
    "pay_item": "Pay item",
    "approved": "Approved",
}


#: The event types whose description is the diff of their two snapshots.
EDIT_EVENT_TYPES = frozenset({"entry_updated", "entry_moved"})


#: ``trusted`` for a write that carries no location to judge: the office's
#: cost-line grid and the leave screen are not My time and send none. Recorded
#: as not checked, which is what trusted means with no company address, so the
#: office's own corrections never read as made away from the workshop.
NOT_CHECKED = True


def is_timesheet_entry(line: CostLine) -> bool:
    """Whether a cost line is a timesheet entry the trail records.

    A line the Leave screen created is an ordinary entry once it exists
    (owner ruling, 2026-10-03); material and adjustment lines are not entries.
    """
    return line.kind == "time" and bool(line.meta.get("created_from_timesheet"))


def snapshot_if_entry(line: CostLine) -> TimesheetLineSnapshot | None:
    """Take the entry's state before a write; None for a line the trail does not record."""
    if not is_timesheet_entry(line):
        return None
    return line_snapshot(line)


def _stored_time(line: CostLine, key: str) -> str | None:
    """Read a start or end time as the workshop drawer stored it (ISO); None where unset."""
    value = line.meta.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Timesheet line {line.id} has a non-string {key}.")
    return value


def _multiplier(line: CostLine, key: str) -> float | None:
    rate = rate_from_meta(line.meta, key)
    return None if rate is None else float(rate)


def line_snapshot(line: CostLine) -> TimesheetLineSnapshot:
    """Read the entry's reader-visible state; raises on a shape a time line cannot have."""
    subtype = line.labour_subtype
    if subtype is None:
        raise ValueError(f"Timesheet line {line.id} has no labour subtype.")
    billable = line.meta.get("is_billable")
    if billable is not None and not isinstance(billable, bool):
        raise ValueError(f"Timesheet line {line.id} has a non-boolean is_billable.")
    job = line.cost_set.job
    pay_item = line.xero_pay_item
    return {
        "job": f"#{job.job_number}",
        "date": line.accounting_date.isoformat(),
        "start_time": _stored_time(line, "start_time"),
        "end_time": _stored_time(line, "end_time"),
        "hours": str(json_safe(line.quantity.quantize(HOURS))),
        "description": line.desc,
        "labour_type": subtype.name,
        "wage_multiplier": _multiplier(line, "wage_rate_multiplier"),
        "invoice_multiplier": _multiplier(line, "bill_rate_multiplier"),
        "billable": billable,
        "wage_rate": str(json_safe(line.unit_cost.quantize(MONEY))),
        "charge_out_rate": str(json_safe(line.unit_rev.quantize(MONEY))),
        "pay_item": pay_item.name if pay_item is not None else None,
        "approved": line.approved,
    }


def _labelled(changes: list[FieldChange]) -> list[FieldChange]:
    return [{**change, "field_name": SNAPSHOT_LABELS[change["field_name"]]} for change in changes]


def record_timesheet_event(
    *,
    staff: Staff,
    event_type: str,
    line: CostLine,
    before: TimesheetLineSnapshot | None,
    trusted: bool,
) -> TimesheetEvent | None:
    """Record one write to ``line``; the one place that decides whether a line is recorded.

    ``trusted`` is whether the write was made at the workshop, by the one rule
    in ``location.saved_remotely``; the caller passes its answer so a write
    and its evidence are judged on the same position.

    Call it inside the write's transaction, after the write for a create,
    edit, move or approval and before the row goes for a delete (Django clears
    the pk on the instance it deleted, and the event names the line by that
    id). ``before`` is ``snapshot_if_entry`` taken before the write; a
    creation has none. Returns None for a line that is not a timesheet entry.

    ``detail.changes`` is the labelled diff of the two snapshots for an edit or
    a move, so the event renders as what changed. A creation, deletion or
    approval is the event in itself and renders as its label; its snapshots
    still carry the entry's state, which is why approval records both sides
    rather than diffing them into "Approved changed from 'False' to 'True'".
    """
    if not is_timesheet_entry(line):
        return None
    if line.staff_id is None:
        raise ValueError(f"Timesheet line {line.id} has no staff member.")
    after = None if event_type == "entry_deleted" else line_snapshot(line)
    diffed = event_type in EDIT_EVENT_TYPES
    changes = _labelled(snapshot_changes(before, after)) if diffed else []
    return TimesheetEvent.objects.create(
        staff=staff,
        worker_id=line.staff_id,
        accounting_date=line.accounting_date,
        cost_line_id=line.id,
        event_type=event_type,
        delta_before=before,
        delta_after=after,
        detail={"changes": changes},
        trusted=trusted,
    )


class DaySnapshot(TypedDict):
    """A person's clock times as a day event records them, "HH:MM" or None."""

    clock_in: str | None
    clock_out: str | None


#: How each day snapshot key reads in ``detail.changes`` and the history panel.
DAY_LABELS: dict[str, str] = {"clock_in": "Clock in", "clock_out": "Clock out"}


def record_day_event(  # noqa: PLR0913 -- keyword-only: who, whose day, which day, what, the two sides, and where
    *,
    staff: Staff,
    worker: Staff,
    day: date,
    event_type: str,
    before: DaySnapshot | None,
    after: DaySnapshot | None,
    trusted: bool,
) -> TimesheetEvent:
    """Record an event of the day itself: a clock tap, times set, standard hours, the day sent.

    The sibling of ``record_timesheet_event`` for what has no entry. The two
    snapshots are the day's clock times; the diff of them is what the panel
    reads, so a tap reads "Clock in 07:02" and a correction "Clock in moved
    from 07:02 to 07:00". An event that moves no time (the day sent) reads
    as its label.
    """
    changes = [
        {**change, "field_name": DAY_LABELS[change["field_name"]]}
        for change in snapshot_changes(before, after)
    ]
    return TimesheetEvent.objects.create(
        staff=staff,
        worker=worker,
        accounting_date=day,
        cost_line_id=None,
        event_type=event_type,
        detail={"changes": changes},
        trusted=trusted,
    )
