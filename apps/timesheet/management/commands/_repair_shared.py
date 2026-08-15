"""Shared plumbing for the timesheet repair commands.

The repair commands construct actual time CostLines outside the interactive
pricing pipeline (``apps/job/services/time_entry_rates.price_time_entry``):
that pipeline derives rates from job and staff configuration, while a repair
writes the exact unit cost the operator reviewed, with revenue pinned to zero
(payroll-backfill work is never billable). One builder serves every repair
command; v1 carried two near-identical siblings (ADR 0039).

Layer contract: ``XeroPayItem`` lives in ``apps.xero``, above the domain apps,
so it is resolved through Django's app registry behind the ``PayItem``
protocol (the pattern ``apps/job/services/time_entry_rates.py`` uses). The
CostLine FK is assigned by id, so the concrete model class is never needed.
"""

import csv
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from django.core.management.base import CommandError, CommandParser

from apps.accounts.models import Staff
from apps.core.xero_registry import xero_model_manager
from apps.job.models.costing import CostLine, CostSet
from apps.job.services.time_entry_rates import PayItem
from apps.timesheet.services.xero_hours import LEAVE_JOB_NAMES


class _PayItemQuery(Protocol):
    """The queryset surface the pay-item lookups need."""

    def first(self) -> PayItem | None:
        """Return the first matching pay item, or None when there is none."""


class _PayItemLookup(Protocol):
    """The manager surface the pay-item lookups need off XeroPayItem."""

    def filter(self, **kwargs: object) -> _PayItemQuery:
        """Return the pay items matching the given lookups."""


def _pay_items() -> _PayItemLookup:
    """Narrow the shared xero-registry seam to this module's protocol."""
    return cast("_PayItemLookup", xero_model_manager("XeroPayItem"))


def get_overtime_pay_item() -> PayItem:
    """Return the time-and-a-half earnings rate, refusing when it is missing."""
    pay_item = _pay_items().filter(name="Time and one half", multiplier=Decimal("1.50")).first()
    if pay_item is None:
        raise CommandError("XeroPayItem 'Time and one half' with multiplier=1.50 not found")
    return pay_item


def get_ordinary_pay_item() -> PayItem:
    """Return the ordinary-time earnings rate, refusing when it is missing."""
    pay_item = _pay_items().filter(name="Ordinary Time", multiplier=Decimal("1.00")).first()
    if pay_item is None:
        raise CommandError("XeroPayItem 'Ordinary Time' with multiplier=1.00 not found")
    return pay_item


def get_leave_pay_items() -> dict[str, PayItem]:
    """Return leave job name -> leave-API pay item for every leave type that has one."""
    result: dict[str, PayItem] = {}
    for name in LEAVE_JOB_NAMES:
        pay_item = _pay_items().filter(name=name, uses_leave_api=True).first()
        if pay_item is not None:
            result[name] = pay_item
    return result


def get_earnings_pay_item_by_name(name: str) -> PayItem:
    """Return the named earnings rate (multiplier set), refusing when it is missing."""
    pay_item = _pay_items().filter(name=name, multiplier__isnull=False).first()
    if pay_item is None:
        raise CommandError(f"XeroPayItem '{name}' not found")
    return pay_item


def add_preview_apply_arguments(parser: CommandParser) -> None:
    """Register the shared two-step workflow flags."""
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate a CSV of proposed changes for review (step 1)",
    )
    parser.add_argument(
        "--apply",
        type=str,
        metavar="CSV_PATH",
        help="Read reviewed CSV and apply the changes (step 2)",
    )


def resolve_preview_or_apply(
    options: Mapping[str, object], *, command: str, default_csv: str
) -> str | None:
    """Return the apply CSV path, or None for the preview step; refuse ambiguity."""
    preview = options.get("preview")
    if not isinstance(preview, bool):
        raise TypeError("The preview option must be a boolean")
    apply_path = options.get("apply")
    if apply_path is not None and not isinstance(apply_path, str):
        raise TypeError("The apply option must be a string path")

    if apply_path is None:
        if not preview:
            raise CommandError(
                f"Specify --preview (step 1) or --apply <csv_path> (step 2)\n"
                f"  Step 1: python manage.py {command} --preview\n"
                f"  Step 2: python manage.py {command} --apply {default_csv}"
            )
        return None
    if preview:
        raise CommandError("Use --preview OR --apply, not both")
    return apply_path


def read_reviewed_csv(
    csv_path: str, required_columns: Sequence[str]
) -> tuple[Path, list[dict[str, str]]]:
    """Read an operator-reviewed CSV, refusing missing files, columns, or rows."""
    path = Path(csv_path)
    if not path.exists():
        raise CommandError(f"CSV file not found: {path}")
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = set(required_columns) - set(reader.fieldnames or [])
        if missing:
            raise CommandError(f"CSV is missing required columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise CommandError("CSV file is empty")
    return path, rows


def write_preview_csv(path: Path, columns: Sequence[str], entries: list[dict[str, str]]) -> None:
    """Write the proposed entries for operator review."""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(entries)


def parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD operator input, refusing anything else."""
    parts = value.strip().split("-")
    if len(parts) != 3:
        raise CommandError(f"Invalid date format: {value}. Use YYYY-MM-DD.")
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise CommandError(f"Invalid date: {value}. Use YYYY-MM-DD.") from exc


def parse_decimal(value: str) -> Decimal:
    """Parse a decimal operator input, refusing anything else."""
    try:
        return Decimal(value.strip())
    except InvalidOperation as exc:
        raise CommandError(f"Invalid decimal value: {value}") from exc


def build_repair_time_line(  # noqa: PLR0913 -- a builder: every field is an axis a repair sets
    staff: Staff,
    cost_set: CostSet,
    *,
    desc: str,
    hours: Decimal,
    unit_cost: Decimal,
    accounting_date: date,
    pay_item_id: UUID,
    wage_rate_multiplier: float,
) -> CostLine:
    """Build — but not save — one repair time CostLine.

    Full model validation runs inside ``CostLine.save()`` (which also assigns
    ``entry_seq``, so it cannot run earlier); the guard here exists to give
    the operator a named-staff error instead of a ValidationError dump.
    """
    if staff.default_labour_subtype is None:
        raise CommandError(
            f"Staff '{staff.get_display_full_name()}' has no default_labour_subtype set"
        )
    return CostLine(
        cost_set=cost_set,
        kind="time",
        desc=desc,
        quantity=hours,
        unit_cost=unit_cost,
        unit_rev=Decimal("0"),
        accounting_date=accounting_date,
        staff=staff,
        xero_pay_item_id=pay_item_id,
        labour_subtype=staff.default_labour_subtype,
        meta={
            "staff_id": str(staff.id),
            "date": accounting_date.isoformat(),
            "is_billable": False,
            "created_from_timesheet": True,
            "wage_rate_multiplier": wage_rate_multiplier,
        },
    )
