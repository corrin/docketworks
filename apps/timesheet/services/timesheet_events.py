"""Event writes for the timesheet domain — the one place its audit rows are made.

Every write to a timesheet entry, on the office cost-line path and the
workshop self-service path alike, records one ``TimesheetEvent`` inside the
same transaction as the row write, so an entry change and its evidence
commit or roll back together. The before/after snapshots are the entry as a
reader sees it: job number, hours, rates, multipliers, pay item, approval.
"""

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


def is_timesheet_entry(line: CostLine) -> bool:
    """Whether a cost line is a timesheet entry the trail records.

    Leave-managed lines are written in batches by a leave request, whose row
    carries its own author; material and adjustment lines are not timesheet
    entries at all.
    """
    return (
        line.kind == "time"
        and bool(line.meta.get("created_from_timesheet"))
        and line.managed_by is None
    )


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
    after: TimesheetLineSnapshot | None,
) -> TimesheetEvent:
    """Write one audit event for ``line``; call it inside the write's transaction.

    ``detail.changes`` is the labelled diff of the two snapshots for an edit or
    a move, so the event renders as what changed. A creation, deletion or
    approval is the event in itself and renders as its label; its snapshots
    still carry the entry's state, which is why approval records both sides
    rather than diffing them into "Approved changed from 'False' to 'True'".
    """
    if line.staff_id is None:
        raise ValueError(f"Timesheet line {line.id} has no staff member.")
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
    )
