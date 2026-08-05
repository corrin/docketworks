"""Workshop "my time" self-service for a staff member's own entries.

Any authenticated staff member may read and write ONLY their own entries;
every write enforces ownership by comparing ``meta.staff_id``.

Rate resolution goes through the one pipeline in
``apps.job.services.time_entry_rates`` (ADR 0039). Resolving a pay item from the
wage multiplier alone is rejected because leave must use the job's leave pay
item and a zero bill rate.
"""

import logging
from datetime import date, datetime, time
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.job_service import get_or_create_cost_set
from apps.job.services.time_entry_rates import (
    ZERO_MULTIPLIER,
    normalize_multiplier,
    price_time_entry,
)

logger = logging.getLogger(__name__)


class EntryOwnershipError(Exception):
    """A staff member touched an entry that is not theirs (403 at the boundary)."""


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
    created_at: datetime
    updated_at: datetime


class WorkshopSummaryData(TypedDict):
    """Data contract for WorkshopSummaryData."""

    total_hours: float
    billable_hours: float
    non_billable_hours: float
    total_cost: float
    total_revenue: float


class WorkshopDayData(TypedDict):
    """Data contract for WorkshopDayData."""

    date: date
    entries: list[WorkshopEntryData]
    summary: WorkshopSummaryData


def resolve_entry_date(date_param: str | None) -> date:
    """Parse the optional ``date`` query parameter; today when absent."""
    if not date_param:
        return timezone.localdate()
    parsed = parse_date(date_param)
    if parsed is None:
        raise ValueError("date must be provided in YYYY-MM-DD format.")
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
    """Read a multiplier out of ``meta``, falling back to ``default``."""
    raw = meta.get(key)
    if raw is None:
        return default
    return normalize_multiplier(raw, default=default)


def entry_data(line: CostLine) -> WorkshopEntryData:
    """Shape one CostLine as a workshop timesheet entry."""
    job = line.cost_set.job
    meta = line.meta
    wage_multiplier = _meta_multiplier(meta, "wage_rate_multiplier", Decimal("1.00"))
    is_billable = bool(meta.get("is_billable", True))
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
        "created_at": line.created_at,
        "updated_at": line.updated_at,
    }


def _summary(entries: list[CostLine]) -> WorkshopSummaryData:
    """Totals for a staff member's day."""
    total_hours = sum((line.quantity for line in entries), Decimal("0"))
    billable_hours = sum(
        (line.quantity for line in entries if line.meta.get("is_billable", True)),
        Decimal("0"),
    )
    return {
        "total_hours": float(total_hours),
        "billable_hours": float(billable_hours),
        "non_billable_hours": float(total_hours - billable_hours),
        "total_cost": float(sum((line.total_cost for line in entries), Decimal("0"))),
        "total_revenue": float(sum((line.total_rev for line in entries), Decimal("0"))),
    }


def list_entries(staff: Staff, entry_date: date) -> WorkshopDayData:
    """List the staff member's own entries for a date, with the day's summary."""
    entries = list(
        CostLine.objects.filter(
            cost_set__kind="actual",
            kind="time",
            staff=staff,
            accounting_date=entry_date,
        )
        .select_related("cost_set__job__company")
        .order_by("entry_seq")
    )
    return {
        "date": entry_date,
        "entries": [entry_data(line) for line in entries],
        "summary": _summary(entries),
    }


def _pricing_meta(
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


def _update_latest_actual(job: Job, cost_set_rev: int, cost_set_id: UUID, staff: Staff) -> None:
    """Point the job at its newest actual cost set."""
    if job.latest_actual is None or cost_set_rev >= job.latest_actual.rev:
        job.latest_actual_id = cost_set_id
        job.save(staff=staff, update_fields=["latest_actual", "updated_at"])


def create_entry(staff: Staff, data: WorkshopEntryCreateData) -> WorkshopEntryData:
    """Create a time line for the authenticated staff member."""
    job = Job.objects.select_related("company", "default_xero_pay_item").get(id=data["job_id"])
    wage_rate_multiplier = data.get("wage_rate_multiplier", Decimal("1.0"))

    with transaction.atomic():
        cost_set = get_or_create_cost_set(job, "actual")
        meta = _pricing_meta(
            staff=staff,
            accounting_date=data["accounting_date"],
            wage_rate_multiplier=wage_rate_multiplier,
            bill_rate_multiplier=data.get("bill_rate_multiplier"),
            is_billable=data.get("is_billable", True),
        )
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        if start_time is not None:
            meta["start_time"] = _format_time(start_time)
        if end_time is not None:
            meta["end_time"] = _format_time(end_time)

        pricing = price_time_entry(job=job, staff=staff, meta=meta)
        meta.update(pricing.meta_updates())

        line = CostLine(
            cost_set=cost_set,
            kind="time",
            desc=data.get("description") or None,
            quantity=data["hours"],
            unit_cost=pricing.unit_cost,
            unit_rev=pricing.unit_rev,
            accounting_date=data["accounting_date"],
            staff=staff,
            xero_pay_item_id=pricing.pay_item.id,
            labour_subtype=pricing.labour_subtype,
            ext_refs={},
            meta=meta,
            # v1: lines booked by workshop staff await office approval.
            approved=staff.is_office_staff,
        )
        line.save()
        _update_latest_actual(job, cost_set.rev, cost_set.id, staff)

    return entry_data(line)


def _owned_line(staff: Staff, entry_id: UUID) -> CostLine:
    """Fetch a time line and assert the staff member owns it."""
    line = CostLine.objects.select_related(
        "cost_set__job__company", "cost_set__job__default_xero_pay_item"
    ).get(id=entry_id, kind="time")
    if line.meta.get("staff_id") != str(staff.id):
        raise EntryOwnershipError("You can only update your own timesheet entries.")
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


def update_entry(staff: Staff, data: WorkshopEntryUpdateData) -> WorkshopEntryData:
    """Update one of the staff member's own entries."""
    line = _owned_line(staff, data["entry_id"])

    with transaction.atomic():
        meta = dict(line.meta)
        changed = _apply_scalar_changes(line, meta, data)
        reprice = _apply_billing_changes(meta, data)

        job = line.cost_set.job
        moved_cost_set = None
        if "job_id" in data and data["job_id"] != job.id:
            job = Job.objects.select_related("company", "default_xero_pay_item").get(
                id=data["job_id"]
            )
            moved_cost_set = get_or_create_cost_set(job, "actual")
            line.cost_set = moved_cost_set
            changed = True
            reprice = True

        if reprice:
            pricing = price_time_entry(
                job=job, staff=staff, meta=meta, labour_subtype=line.labour_subtype
            )
            meta.update(pricing.meta_updates())
            line.unit_cost = pricing.unit_cost
            line.unit_rev = pricing.unit_rev
            line.xero_pay_item_id = pricing.pay_item.id
            line.labour_subtype = pricing.labour_subtype
            changed = True

        if not changed:
            raise ValueError("No changes supplied.")

        line.meta = meta
        line.save()
        if moved_cost_set is not None:
            _update_latest_actual(job, moved_cost_set.rev, moved_cost_set.id, staff)

    return entry_data(line)


def delete_entry(staff: Staff, entry_id: UUID) -> None:
    """Delete one of the staff member's own entries."""
    line = CostLine.objects.get(id=entry_id, kind="time")
    if line.meta.get("staff_id") != str(staff.id):
        raise EntryOwnershipError("You can only delete your own timesheet entries.")
    line.delete()
    logger.info("Deleted workshop timesheet entry %s for staff %s", entry_id, staff.id)
