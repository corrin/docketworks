"""Shared plumbing for the timesheet repair commands.

The repair commands write time through the one entry writer
(``apps/timesheet/services/workshop_timesheet_service``), which prices every
line through ``price_time_entry``: the wage times the multiplier, and the pay
item the multiplier names. A repair never prices a line itself.

Layer contract: ``XeroPayItem`` lives in ``apps.xero``, above the domain apps,
so it is resolved through Django's app registry behind the ``PayItem``
protocol (the pattern ``apps/job/services/time_entry_rates.py`` uses).
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
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.job.services.time_entry_rates import PayItem
from apps.timesheet.services.approval import approve_line
from apps.timesheet.services.workshop_timesheet_service import (
    day_time_lines,
    is_general_work_fill,
)


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


def add_actor_argument(parser: CommandParser) -> None:
    """Register who makes the repair: the writer records them against every change."""
    parser.add_argument(
        "--actor",
        type=str,
        metavar="EMAIL",
        help="Email of the office staff member making the repair (needed to write)",
    )


def resolve_actor(options: Mapping[str, object]) -> Staff:
    """Return the office staff member the repair is made by, refusing anyone else."""
    email = options.get("actor")
    if not isinstance(email, str):
        raise CommandError("Name who is making the repair: --actor <office staff email>")
    actor = Staff.objects.sole_login_match(email)
    if actor is None:
        raise CommandError(f"No single staff member has the email {email}")
    if not actor.is_office_staff:
        raise CommandError(f"{actor.get_display_full_name()} is not office staff")
    return actor


def day_line_ids(owner: Staff, day: date) -> set[UUID]:
    """Return the ids of the person's time lines on the day, before a write."""
    return {line.id for line in day_time_lines(owner, day)}


def written_entries(owner: Staff, day: date, untouched: set[UUID]) -> list[CostLine]:
    """Return the entries a write put on the day: the new lines, less rebuilt General work."""
    return [
        line
        for line in day_time_lines(owner, day)
        if line.id not in untouched and not is_general_work_fill(line)
    ]


def approve_written(actor: Staff, owner: Staff, day: date, untouched: set[UUID]) -> None:
    """Approve the day's waiting lines the repair wrote: every one not in ``untouched``.

    A repair lines a week up with what Xero paid, and Xero pays approved time
    only, so what it writes is approved. The writer leaves its lines waiting,
    may split an entry at the overtime point and rebuilds a filled day's
    General work, so the lines are found on the day. Leave and other
    workflow-managed lines are approved when made.
    """
    # His lock, then the jobs', the order every write to his day takes them.
    Staff.objects.select_for_update().filter(pk=owner.pk).first()
    waiting = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
        staff=owner,
        accounting_date=day,
        approved=False,
        managed_by=None,
    ).exclude(id__in=untouched)
    lock_costing_jobs(set(waiting.values_list("cost_set__job_id", flat=True)))
    for line in waiting.select_for_update(of=("self",)).select_related(
        "cost_set__job", "labour_subtype", "xero_pay_item"
    ):
        approve_line(line, actor)
