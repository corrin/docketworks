"""Reclassify standard-rate CostLine entries as overtime to match Xero payroll.

Handles staff-weeks where local total hours match Xero total hours (no
headroom) but local OT < Xero OT. In these cases, existing standard-rate
entries on special/shop jobs are reclassified as overtime. When only part of
an entry is needed, it is split — the original is reduced and a new OT entry
is created for the remainder. The companion for the headroom case is
``create_overtime_entries``.

Two-step workflow:
  1. Preview: generate a CSV of proposed reclassifications for review/editing
     python manage.py reclassify_overtime_entries --preview

  2. Apply: read the reviewed CSV and reclassify entries
     python manage.py reclassify_overtime_entries \
         --apply scripts/overtime_reclassify_preview.csv --actor <office staff email>

The entry writer reprices each changed line at the worker's wage times 1.5,
keeping the line's charge rate; a line that was approved is approved again.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.accounts.models import Staff
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import (
    OVERTIME_MULTIPLIER,
    ZERO_MULTIPLIER,
    get_bill_rate_multiplier,
    rate_from_meta,
)
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopEntryCreateData,
    create_entry,
    update_entry,
)
from apps.timesheet.services.xero_hours import (
    XeroWeekRow,
    build_staff_lookup,
    get_jm_hours_for_staff_week,
    get_xero_hours_by_staff_week,
    leave_job_ids,
)

from ._repair_shared import (
    add_actor_argument,
    add_preview_apply_arguments,
    approve_written,
    day_line_ids,
    parse_decimal,
    read_reviewed_csv,
    resolve_actor,
    resolve_preview_or_apply,
    write_preview_csv,
    written_entries,
)

DESC_SUFFIX = "[OT reclassified]"

PREVIEW_CSV_PATH = (
    Path(__file__).resolve().parents[4] / "scripts" / "overtime_reclassify_preview.csv"
)

PREVIEW_COLUMNS = [
    "week_start",
    "staff_name",
    "staff_id",
    "costline_id",
    "action",
    "ot_hours",
    "remaining_hours",
    "accounting_date",
    "job_name",
    "job_id",
    "unit_cost",
    "xero_ot",
    "jm_ot",
    "ot_gap",
]

# A CSV round-trips quantities through text, so equality checks carry the
# same one-cent-of-an-hour tolerance v1 used rather than exact Decimal match.
QUANTITY_TOLERANCE = Decimal("0.01")

THREE_DP = Decimal("0.001")


class _UnfillableGap(TypedDict):
    """A staff-week whose OT gap exceeds its eligible standard-rate hours."""

    week_start: date
    staff_name: str
    remaining: Decimal
    ot_gap: Decimal


class _ValidatedRow(TypedDict):
    """One CSV row, validated against the live CostLine, awaiting the write."""

    costline: CostLine
    owner: Staff
    action: str
    ot_hours: Decimal
    remaining_hours: Decimal
    staff_name: str
    week_start: str


class Command(BaseCommand):
    """Two-step (preview CSV, then apply) OT reclassification of existing lines."""

    help = "Reclassify standard-rate entries as overtime to match Xero payroll OT hours"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the two workflow steps."""
        add_preview_apply_arguments(parser)
        add_actor_argument(parser)

    def handle(self, *_args: object, **options: object) -> None:
        """Dispatch to the preview or apply step."""
        apply_path = resolve_preview_or_apply(
            options,
            command="reclassify_overtime_entries",
            default_csv="scripts/overtime_reclassify_preview.csv",
        )
        if apply_path is None:
            self._do_preview()
        else:
            self._do_apply(apply_path, resolve_actor(options))

    # ------------------------------------------------------------------ #
    #  STEP 1: Preview
    # ------------------------------------------------------------------ #

    def _do_preview(self) -> None:
        """Find OT gaps without headroom and write the proposed reclassifications."""
        staff_by_xero_id = build_staff_lookup()
        xero_rows = get_xero_hours_by_staff_week()

        entries: list[dict[str, str]] = []
        skipped_matched = 0
        skipped_has_headroom = 0
        skipped_no_staff = 0
        unfillable_gaps: list[_UnfillableGap] = []

        for row in xero_rows:
            staff = staff_by_xero_id.get(row["xero_employee_id"])
            if staff is None:
                skipped_no_staff += 1
                continue

            xero_total = row["ordinary_hrs"] + row["ot_hrs"] + row["leave_hrs"]
            jm_data = get_jm_hours_for_staff_week(str(staff.id), row["week_start"])
            headroom = xero_total - jm_data["jm_total"]
            ot_gap = row["ot_hrs"] - jm_data["jm_ot"]

            if ot_gap <= 0:
                skipped_matched += 1
                continue
            if headroom > 0:
                skipped_has_headroom += 1
                continue

            week_entries, remaining_gap = self._week_reclassifications(
                row, str(staff.id), staff.get_display_name(), jm_data["jm_ot"], ot_gap
            )
            entries.extend(week_entries)
            if remaining_gap > 0:
                unfillable_gaps.append(
                    _UnfillableGap(
                        week_start=row["week_start"],
                        staff_name=staff.get_display_name(),
                        remaining=remaining_gap,
                        ot_gap=ot_gap,
                    )
                )

        self._report_and_write_preview(
            entries,
            unfillable_gaps,
            xero_rows_processed=len(xero_rows),
            skipped_no_staff=skipped_no_staff,
            skipped_matched=skipped_matched,
            skipped_has_headroom=skipped_has_headroom,
        )

    def _week_reclassifications(
        self,
        row: XeroWeekRow,
        staff_id: str,
        staff_name: str,
        jm_ot: Decimal,
        ot_gap: Decimal,
    ) -> tuple[list[dict[str, str]], Decimal]:
        """Propose reclassify/split rows for one week; returns (rows, unfilled gap)."""
        week_entries: list[dict[str, str]] = []
        remaining_gap = ot_gap
        for candidate in self._get_reclassify_candidates(staff_id, row["week_start"]):
            if remaining_gap <= 0:
                break
            if candidate.quantity <= remaining_gap:
                action = "reclassify"
                ot_hours = candidate.quantity
                remaining_hours = Decimal("0")
                remaining_gap -= candidate.quantity
            else:
                action = "split"
                ot_hours = remaining_gap
                remaining_hours = candidate.quantity - remaining_gap
                remaining_gap = Decimal("0")
            week_entries.append(
                {
                    "week_start": row["week_start"].isoformat(),
                    "staff_name": staff_name,
                    "staff_id": staff_id,
                    "costline_id": str(candidate.id),
                    "action": action,
                    "ot_hours": str(ot_hours),
                    "remaining_hours": str(remaining_hours),
                    "accounting_date": candidate.accounting_date.isoformat(),
                    "job_name": candidate.cost_set.job.name,
                    "job_id": str(candidate.cost_set.job.id),
                    "unit_cost": str(candidate.unit_cost),
                    "xero_ot": str(row["ot_hrs"]),
                    "jm_ot": str(jm_ot),
                    "ot_gap": str(ot_gap),
                }
            )
        return week_entries, remaining_gap

    def _report_and_write_preview(  # noqa: PLR0913 -- a report: each counter is one summary line
        self,
        entries: list[dict[str, str]],
        unfillable_gaps: list[_UnfillableGap],
        *,
        xero_rows_processed: int,
        skipped_no_staff: int,
        skipped_matched: int,
        skipped_has_headroom: int,
    ) -> None:
        """Summarise the proposal and write the review CSV."""
        self.stdout.write(f"\nXero rows processed: {xero_rows_processed}")
        self.stdout.write(f"Skipped (no staff match): {skipped_no_staff}")
        self.stdout.write(f"Skipped (OT already matched): {skipped_matched}")
        self.stdout.write(
            f"Skipped (has headroom — use create_overtime_entries): {skipped_has_headroom}"
        )
        self.stdout.write(f"Entries to reclassify/split: {len(entries)}")

        if unfillable_gaps:
            self.stdout.write(
                self.style.WARNING(
                    f"\nUnfillable gaps (not enough eligible entries): {len(unfillable_gaps)}"
                )
            )
            for gap in unfillable_gaps:
                self.stdout.write(
                    f"  {gap['week_start']} | {gap['staff_name']} | "
                    f"unfilled: {gap['remaining']}h of {gap['ot_gap']}h OT gap"
                )

        if not entries:
            self.stdout.write("Nothing to reclassify.")
            return

        write_preview_csv(PREVIEW_CSV_PATH, PREVIEW_COLUMNS, entries)

        self.stdout.write(self.style.SUCCESS(f"\nPreview written to: {PREVIEW_CSV_PATH}"))
        self.stdout.write(
            "Review/edit the CSV, then run:\n"
            "  python manage.py reclassify_overtime_entries "
            f"--apply {PREVIEW_CSV_PATH} --actor <office staff email>"
        )

    # ------------------------------------------------------------------ #
    #  STEP 2: Apply
    # ------------------------------------------------------------------ #

    def _do_apply(self, csv_path: str, actor: Staff) -> None:
        """Reclassify/split the entries a reviewed CSV describes, all-or-nothing."""
        path, rows = read_reviewed_csv(csv_path, PREVIEW_COLUMNS)
        self.stdout.write(f"Read {len(rows)} entries from {path}")

        validated = [self._validate_row(i, row) for i, row in enumerate(rows, 1)]
        self.stdout.write(f"Validated {len(validated)} entries.\n")

        reclassified_count = 0
        split_count = 0
        with transaction.atomic():
            for entry in validated:
                costline = entry["costline"]
                owner, day = entry["owner"], costline.accounting_date
                untouched = day_line_ids(owner, day) - {costline.id}
                if entry["action"] == "reclassify":
                    self._reclassify_costline(actor, costline)
                    reclassified_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Reclassified: {entry['week_start']} | "
                            f"{entry['staff_name']} | {entry['ot_hours']}h OT | "
                            f"job: {costline.cost_set.job.name} | ID: {costline.id}"
                        )
                    )
                else:
                    self._split_costline(actor, owner, costline, entry["ot_hours"])
                    split_count += 1
                    new_ids = [
                        str(line.id)
                        for line in written_entries(owner, day, untouched | {costline.id})
                    ]
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Split: {entry['week_start']} | "
                            f"{entry['staff_name']} | "
                            f"{entry['ot_hours']}h OT (new ID: {', '.join(new_ids)}) | "
                            f"{entry['remaining_hours']}h kept ordinary | "
                            f"job: {costline.cost_set.job.name}"
                        )
                    )
                # Xero paid the week: what was approved before the repair stays so.
                if costline.approved:
                    approve_written(actor, owner, day, untouched)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Reclassified: {reclassified_count}, "
                f"Split: {split_count}, "
                f"Total: {reclassified_count + split_count}"
            )
        )

    @staticmethod
    def _validate_row(row_number: int, row: dict[str, str]) -> _ValidatedRow:
        """Validate one CSV row against the live CostLine it targets."""
        action = row["action"].strip()
        if action not in ("reclassify", "split"):
            raise CommandError(
                f"Row {row_number}: action must be 'reclassify' or 'split', got '{action}'"
            )

        ot_hours = parse_decimal(row["ot_hours"])
        remaining_hours = parse_decimal(row["remaining_hours"])
        if ot_hours <= 0:
            raise CommandError(f"Row {row_number}: ot_hours must be positive, got {ot_hours}")
        if action == "split" and remaining_hours <= 0:
            raise CommandError(
                f"Row {row_number}: remaining_hours must be positive for split, "
                f"got {remaining_hours}"
            )

        costline_id = row["costline_id"].strip()
        try:
            costline = CostLine.objects.select_related(
                "cost_set", "cost_set__job", "xero_pay_item", "staff"
            ).get(id=costline_id)
        except CostLine.DoesNotExist as exc:
            raise CommandError(f"Row {row_number}: CostLine not found: {costline_id}") from exc

        # Refuses by the pay-item multiplier, mirroring _get_reclassify_candidates'
        # exclusion, not by looking for DESC_SUFFIX in desc: desc is operator-editable
        # text, the pay item is what payroll reads. Without this, re-running a reviewed
        # CSV re-reclassifies every whole-line row (the quantity check still passes)
        # and stacks the suffix.
        if (
            costline.xero_pay_item is not None
            and costline.xero_pay_item.multiplier is not None
            and costline.xero_pay_item.multiplier > Decimal("1")
        ):
            raise CommandError(
                f"Row {row_number}: CostLine {costline_id} is already at an overtime "
                f"rate ({costline.xero_pay_item.name}, x{costline.xero_pay_item.multiplier}) "
                "— this CSV row has already been applied"
            )

        expected_total = ot_hours + remaining_hours
        if action == "split" and abs(costline.quantity - expected_total) > QUANTITY_TOLERANCE:
            raise CommandError(
                f"Row {row_number}: ot_hours ({ot_hours}) + remaining_hours "
                f"({remaining_hours}) = {expected_total} does not match "
                f"CostLine quantity ({costline.quantity})"
            )
        if action == "reclassify" and abs(costline.quantity - ot_hours) > QUANTITY_TOLERANCE:
            raise CommandError(
                f"Row {row_number}: ot_hours ({ot_hours}) does not match "
                f"CostLine quantity ({costline.quantity}) for reclassify action"
            )

        if costline.staff is None:
            raise CommandError(f"Row {row_number}: CostLine {costline_id} has no staff member")
        return _ValidatedRow(
            costline=costline,
            owner=costline.staff,
            action=action,
            ot_hours=ot_hours,
            remaining_hours=remaining_hours,
            staff_name=row["staff_name"],
            week_start=row["week_start"],
        )

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_reclassify_candidates(staff_id: str, week_start: date) -> list[CostLine]:
        """Find standard-rate CostLines on special/shop jobs for this staff-week.

        Returns candidates sorted by most recent accounting_date first.
        """
        week_end = week_start + timedelta(days=6)
        return list(
            CostLine.objects.filter(
                kind="time",
                cost_set__kind="actual",
                cost_set__job__status="special",
                accounting_date__gte=week_start,
                accounting_date__lte=week_end,
                staff_id=staff_id,
            )
            .exclude(cost_set__job_id__in=leave_job_ids())
            # Entries already at an overtime rate are not reclassification fodder.
            .exclude(xero_pay_item__multiplier__gt=Decimal("1"))
            .select_related("cost_set", "cost_set__job")
            .order_by("-accounting_date")
        )

    @staticmethod
    def _reclassify_costline(actor: Staff, costline: CostLine) -> None:
        """Reclassify a whole CostLine as overtime."""
        update_entry(
            actor,
            {
                "entry_id": costline.id,
                "description": _reclassified(costline),
                "wage_rate_multiplier": OVERTIME_MULTIPLIER,
                "bill_rate_multiplier": _kept_charge(costline),
            },
        )

    @staticmethod
    def _split_costline(actor: Staff, owner: Staff, costline: CostLine, ot_hours: Decimal) -> None:
        """Split a CostLine: reduce the original, create a new OT entry for the rest."""
        bill_rate_multiplier = _kept_charge(costline)
        update_entry(
            actor,
            {
                "entry_id": costline.id,
                "hours": (costline.quantity - ot_hours).quantize(THREE_DP),
            },
        )
        data: WorkshopEntryCreateData = {
            "job_id": costline.cost_set.job_id,
            "accounting_date": costline.accounting_date,
            "hours": ot_hours.quantize(THREE_DP),
            "description": _reclassified(costline),
            "wage_rate_multiplier": OVERTIME_MULTIPLIER,
            "bill_rate_multiplier": bill_rate_multiplier,
            "is_billable": bill_rate_multiplier > ZERO_MULTIPLIER,
        }
        if costline.labour_subtype_id is not None:
            data["labour_subtype_id"] = costline.labour_subtype_id
        create_entry(actor, owner, data)


def _reclassified(line: CostLine) -> str:
    """Return the line's description, marked as reclassified to overtime."""
    return f"{line.desc} {DESC_SUFFIX}" if line.desc else DESC_SUFFIX


def _kept_charge(line: CostLine) -> Decimal:
    """Return the charge rate the line was billed at: a payroll repair does not rebill.

    Left to itself the writer would charge overtime hours at the overtime rate.
    """
    wage = rate_from_meta(line.meta, "wage_rate_multiplier")
    if wage is None or wage <= ZERO_MULTIPLIER:
        raise CommandError(f"Time line {line.id} is unpaid, so it cannot be paid as overtime.")
    return get_bill_rate_multiplier(line.meta, wage)
