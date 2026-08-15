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
         --apply scripts/overtime_reclassify_preview.csv
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import PayItem
from apps.timesheet.services.xero_hours import (
    LEAVE_JOB_NAMES,
    XeroWeekRow,
    build_staff_lookup,
    get_jm_hours_for_staff_week,
    get_xero_hours_by_staff_week,
)

from ._repair_shared import (
    add_preview_apply_arguments,
    get_overtime_pay_item,
    parse_decimal,
    read_reviewed_csv,
    resolve_preview_or_apply,
    write_preview_csv,
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

OT_MULTIPLIER = 1.5


class _UnfillableGap(TypedDict):
    """A staff-week whose OT gap exceeds its eligible standard-rate hours."""

    week_start: date
    staff_name: str
    remaining: Decimal
    ot_gap: Decimal


class _ValidatedRow(TypedDict):
    """One CSV row, validated against the live CostLine, awaiting the write."""

    costline: CostLine
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
            self._do_apply(apply_path)

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
            f"--apply {PREVIEW_CSV_PATH}"
        )

    # ------------------------------------------------------------------ #
    #  STEP 2: Apply
    # ------------------------------------------------------------------ #

    def _do_apply(self, csv_path: str) -> None:
        """Reclassify/split the entries a reviewed CSV describes, all-or-nothing."""
        ot_pay_item = get_overtime_pay_item()
        path, rows = read_reviewed_csv(csv_path, PREVIEW_COLUMNS)
        self.stdout.write(f"Read {len(rows)} entries from {path}")

        validated = [self._validate_row(i, row) for i, row in enumerate(rows, 1)]
        self.stdout.write(f"Validated {len(validated)} entries.\n")

        reclassified_count = 0
        split_count = 0
        with transaction.atomic():
            for entry in validated:
                costline = entry["costline"]
                if entry["action"] == "reclassify":
                    self._reclassify_costline(costline, ot_pay_item)
                    reclassified_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Reclassified: {entry['week_start']} | "
                            f"{entry['staff_name']} | {entry['ot_hours']}h OT | "
                            f"job: {costline.cost_set.job.name} | ID: {costline.id}"
                        )
                    )
                else:
                    new_line = self._split_costline(costline, entry["ot_hours"], ot_pay_item)
                    split_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Split: {entry['week_start']} | "
                            f"{entry['staff_name']} | "
                            f"{entry['ot_hours']}h OT (new ID: {new_line.id}) | "
                            f"{entry['remaining_hours']}h kept ordinary | "
                            f"job: {costline.cost_set.job.name}"
                        )
                    )

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
                "cost_set", "cost_set__job", "xero_pay_item"
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

        return _ValidatedRow(
            costline=costline,
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
            .exclude(cost_set__job__name__in=LEAVE_JOB_NAMES)
            # Entries already at an overtime rate are not reclassification fodder.
            .exclude(xero_pay_item__multiplier__gt=Decimal("1"))
            .select_related("cost_set", "cost_set__job")
            .order_by("-accounting_date")
        )

    @staticmethod
    def _reclassify_costline(costline: CostLine, ot_pay_item: PayItem) -> None:
        """Reclassify a whole CostLine as overtime."""
        costline.xero_pay_item_id = ot_pay_item.id
        costline.desc = f"{costline.desc} {DESC_SUFFIX}"
        meta = dict(costline.meta or {})
        meta["wage_rate_multiplier"] = OT_MULTIPLIER
        costline.meta = meta
        costline.save()

    @staticmethod
    def _split_costline(costline: CostLine, ot_hours: Decimal, ot_pay_item: PayItem) -> CostLine:
        """Split a CostLine: reduce the original, create a new OT entry for the rest."""
        # Reduce original — quantize to 3dp to match DecimalField(10,3).
        costline.quantity = (costline.quantity - ot_hours).quantize(THREE_DP)
        costline.save()

        meta = dict(costline.meta or {})
        meta["wage_rate_multiplier"] = OT_MULTIPLIER
        new_line = CostLine(
            cost_set=costline.cost_set,
            kind=costline.kind,
            desc=f"{costline.desc} {DESC_SUFFIX}",
            quantity=ot_hours.quantize(THREE_DP),
            unit_cost=costline.unit_cost,
            unit_rev=costline.unit_rev,
            accounting_date=costline.accounting_date,
            staff=costline.staff,
            xero_pay_item_id=ot_pay_item.id,
            labour_subtype=costline.labour_subtype,
            meta=meta,
        )
        new_line.save()
        return new_line
