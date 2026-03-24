"""
Reclassify standard-rate CostLine entries as overtime to match Xero payroll OT hours.

Handles staff-weeks where JM total hours ≈ Xero total hours (no headroom) but
JM OT < Xero OT. In these cases, existing standard-rate entries on special/shop
jobs are reclassified as overtime. When only part of an entry is needed, it is
split — the original is reduced and a new OT entry is created for the remainder.

Two-step workflow:
  1. Preview: generate a CSV of proposed reclassifications for review/editing
     python manage.py reclassify_overtime_entries --preview

  2. Apply: read the reviewed CSV and reclassify entries
     python manage.py reclassify_overtime_entries --apply scripts/overtime_reclassify_preview.csv
"""

import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.job.models import CostLine
from apps.timesheet.services.xero_hours import (
    build_staff_lookup,
    get_jm_hours_for_staff_week,
    get_xero_hours_by_staff_week,
)
from apps.workflow.models import XeroPayItem

# Leave job names to exclude from candidate selection
LEAVE_JOB_NAMES = {
    "Annual Leave",
    "Sick Leave",
    "Bereavement Leave",
    "Unpaid Leave",
    "Statutory holiday",
}

DESC_PREFIX = "Reclassified to overtime"

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


class Command(BaseCommand):
    help = "Reclassify standard-rate entries as overtime to match Xero payroll OT hours"

    def add_arguments(self, parser):
        parser.add_argument(
            "--preview",
            action="store_true",
            help="Generate a CSV of proposed reclassifications for review (step 1)",
        )
        parser.add_argument(
            "--apply",
            type=str,
            metavar="CSV_PATH",
            help="Read reviewed CSV and reclassify entries (step 2)",
        )

    def handle(self, *args, **options):
        if options["preview"] and options["apply"]:
            raise CommandError("Use --preview OR --apply, not both")
        if not options["preview"] and not options["apply"]:
            raise CommandError(
                "Specify --preview (step 1) or --apply <csv_path> (step 2)\n"
                "  Step 1: python manage.py reclassify_overtime_entries --preview\n"
                "  Step 2: python manage.py reclassify_overtime_entries "
                "--apply scripts/overtime_reclassify_preview.csv"
            )

        if options["preview"]:
            self._do_preview()
        else:
            self._do_apply(options["apply"])

    # ------------------------------------------------------------------ #
    #  STEP 1: Preview
    # ------------------------------------------------------------------ #

    def _do_preview(self):
        staff_by_xero_id = build_staff_lookup()
        xero_rows = get_xero_hours_by_staff_week()

        entries = []
        skipped_matched = 0
        skipped_has_headroom = 0
        skipped_no_staff = 0
        unfillable_gaps = []

        for row in xero_rows:
            week_start = row["week_start"]
            xero_employee_id = row["xero_employee_id"]

            if xero_employee_id not in staff_by_xero_id:
                skipped_no_staff += 1
                continue

            staff = staff_by_xero_id[xero_employee_id]

            xero_ot_hrs = row["ot_hrs"]
            xero_ordinary_hrs = row["ordinary_hrs"]
            xero_leave_hrs = row["leave_hrs"]
            xero_total = xero_ordinary_hrs + xero_ot_hrs + xero_leave_hrs

            jm_data = get_jm_hours_for_staff_week(str(staff.id), week_start)
            jm_total = jm_data["jm_total"]
            jm_ot = jm_data["jm_ot"]

            headroom = xero_total - jm_total
            ot_gap = xero_ot_hrs - jm_ot

            if ot_gap <= 0:
                skipped_matched += 1
                continue

            if headroom > 0:
                skipped_has_headroom += 1
                continue

            # Find standard-rate candidates on special/shop jobs
            candidates = self._get_reclassify_candidates(str(staff.id), week_start)

            remaining_gap = ot_gap
            week_entries = []

            for cl in candidates:
                if remaining_gap <= 0:
                    break

                if cl.quantity <= remaining_gap:
                    # Reclassify the whole entry
                    week_entries.append(
                        {
                            "week_start": week_start.isoformat(),
                            "staff_name": staff.get_display_name(),
                            "staff_id": str(staff.id),
                            "costline_id": str(cl.id),
                            "action": "reclassify",
                            "ot_hours": str(cl.quantity),
                            "remaining_hours": "0",
                            "accounting_date": cl.accounting_date.isoformat(),
                            "job_name": cl.cost_set.job.name,
                            "job_id": str(cl.cost_set.job.id),
                            "unit_cost": str(cl.unit_cost),
                            "xero_ot": str(xero_ot_hrs),
                            "jm_ot": str(jm_ot),
                            "ot_gap": str(ot_gap),
                        }
                    )
                    remaining_gap -= cl.quantity
                else:
                    # Split: reclassify only what we need
                    keep_hours = cl.quantity - remaining_gap
                    week_entries.append(
                        {
                            "week_start": week_start.isoformat(),
                            "staff_name": staff.get_display_name(),
                            "staff_id": str(staff.id),
                            "costline_id": str(cl.id),
                            "action": "split",
                            "ot_hours": str(remaining_gap),
                            "remaining_hours": str(keep_hours),
                            "accounting_date": cl.accounting_date.isoformat(),
                            "job_name": cl.cost_set.job.name,
                            "job_id": str(cl.cost_set.job.id),
                            "unit_cost": str(cl.unit_cost),
                            "xero_ot": str(xero_ot_hrs),
                            "jm_ot": str(jm_ot),
                            "ot_gap": str(ot_gap),
                        }
                    )
                    remaining_gap = Decimal("0")

            entries.extend(week_entries)

            if remaining_gap > 0:
                unfillable_gaps.append(
                    {
                        "week_start": week_start,
                        "staff_name": staff.get_display_name(),
                        "remaining": remaining_gap,
                        "ot_gap": ot_gap,
                    }
                )

        # Report
        self.stdout.write(f"\nXero rows processed: {len(xero_rows)}")
        self.stdout.write(f"Skipped (no staff match): {skipped_no_staff}")
        self.stdout.write(f"Skipped (OT already matched): {skipped_matched}")
        self.stdout.write(
            f"Skipped (has headroom — use create_overtime_entries): "
            f"{skipped_has_headroom}"
        )
        self.stdout.write(f"Entries to reclassify/split: {len(entries)}")

        if unfillable_gaps:
            self.stdout.write(
                self.style.WARNING(
                    f"\nUnfillable gaps (not enough eligible entries): "
                    f"{len(unfillable_gaps)}"
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

        # Write preview CSV
        with open(PREVIEW_CSV_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=PREVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(entries)

        self.stdout.write(
            self.style.SUCCESS(f"\nPreview written to: {PREVIEW_CSV_PATH}")
        )
        self.stdout.write(
            "Review/edit the CSV, then run:\n"
            "  python manage.py reclassify_overtime_entries "
            f"--apply {PREVIEW_CSV_PATH}"
        )

    # ------------------------------------------------------------------ #
    #  STEP 2: Apply
    # ------------------------------------------------------------------ #

    def _do_apply(self, csv_path: str):
        path = Path(csv_path)
        if not path.exists():
            raise CommandError(f"CSV file not found: {path}")

        ot_pay_item = self._get_ot_pay_item()

        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise CommandError("CSV file is empty")

        self.stdout.write(f"Read {len(rows)} entries from {path}")

        # Pre-fetch and validate all referenced CostLines upfront
        validated = []
        for i, row in enumerate(rows, 1):
            costline_id = row["costline_id"].strip()
            action = row["action"].strip()
            ot_hours = self._parse_decimal(row["ot_hours"])
            remaining_hours = self._parse_decimal(row["remaining_hours"])

            if action not in ("reclassify", "split"):
                raise CommandError(
                    f"Row {i}: action must be 'reclassify' or 'split', "
                    f"got '{action}'"
                )

            if ot_hours <= 0:
                raise CommandError(
                    f"Row {i}: ot_hours must be positive, got {ot_hours}"
                )

            try:
                costline = CostLine.objects.select_related(
                    "cost_set", "cost_set__job"
                ).get(id=costline_id)
            except CostLine.DoesNotExist:
                raise CommandError(f"Row {i}: CostLine not found: {costline_id}")

            if action == "split" and remaining_hours <= 0:
                raise CommandError(
                    f"Row {i}: remaining_hours must be positive for split, "
                    f"got {remaining_hours}"
                )

            expected_total = ot_hours + remaining_hours
            if action == "split" and abs(costline.quantity - expected_total) > Decimal(
                "0.01"
            ):
                raise CommandError(
                    f"Row {i}: ot_hours ({ot_hours}) + remaining_hours "
                    f"({remaining_hours}) = {expected_total} does not match "
                    f"CostLine quantity ({costline.quantity})"
                )

            if action == "reclassify" and abs(costline.quantity - ot_hours) > Decimal(
                "0.01"
            ):
                raise CommandError(
                    f"Row {i}: ot_hours ({ot_hours}) does not match "
                    f"CostLine quantity ({costline.quantity}) for reclassify action"
                )

            validated.append(
                {
                    "costline": costline,
                    "action": action,
                    "ot_hours": ot_hours,
                    "remaining_hours": remaining_hours,
                    "staff_name": row["staff_name"],
                    "week_start": row["week_start"],
                }
            )

        self.stdout.write(f"Validated {len(validated)} entries.\n")

        reclassified_count = 0
        split_count = 0

        with transaction.atomic():
            for entry in validated:
                costline = entry["costline"]
                action = entry["action"]
                ot_hours = entry["ot_hours"]
                staff_name = entry["staff_name"]

                if action == "reclassify":
                    self._reclassify_costline(costline, ot_pay_item)
                    reclassified_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Reclassified: {entry['week_start']} | "
                            f"{staff_name} | {ot_hours}h OT | "
                            f"job: {costline.cost_set.job.name} | ID: {costline.id}"
                        )
                    )

                elif action == "split":
                    new_cl = self._split_costline(
                        costline, ot_hours, ot_pay_item, staff_name
                    )
                    split_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Split: {entry['week_start']} | "
                            f"{staff_name} | {ot_hours}h OT (new ID: {new_cl.id}) | "
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

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _get_reclassify_candidates(
        self, staff_id: str, week_start: date
    ) -> list[CostLine]:
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
                meta__staff_id=staff_id,
            )
            .exclude(cost_set__job__name__in=LEAVE_JOB_NAMES)
            .exclude(
                # Don't reclassify entries already marked as OT
                xero_pay_item__multiplier__gt=Decimal("1"),
            )
            .select_related("cost_set", "cost_set__job")
            .order_by("-accounting_date")
        )

    def _reclassify_costline(self, costline: CostLine, ot_pay_item: XeroPayItem):
        """Reclassify a whole CostLine as overtime."""
        costline.xero_pay_item = ot_pay_item
        costline.desc = f"{costline.desc} [OT reclassified]"
        meta = costline.meta or {}
        meta["wage_rate_multiplier"] = 1.5
        costline.meta = meta
        costline.save()

    def _split_costline(
        self,
        costline: CostLine,
        ot_hours: Decimal,
        ot_pay_item: XeroPayItem,
        staff_name: str,
    ) -> CostLine:
        """Split a CostLine: reduce original, create new OT entry for remainder."""
        # Reduce original — quantize to 3dp to match DecimalField(10,3)
        costline.quantity = (costline.quantity - ot_hours).quantize(Decimal("0.001"))
        costline.save()

        # Create new OT entry copying fields from original
        meta = dict(costline.meta or {})
        meta["wage_rate_multiplier"] = 1.5

        new_cl = CostLine.objects.create(
            cost_set=costline.cost_set,
            kind=costline.kind,
            desc=f"{costline.desc} [OT reclassified]",
            quantity=ot_hours.quantize(Decimal("0.001")),
            unit_cost=costline.unit_cost,
            unit_rev=costline.unit_rev,
            accounting_date=costline.accounting_date,
            xero_pay_item=ot_pay_item,
            meta=meta,
        )
        return new_cl

    def _get_ot_pay_item(self) -> XeroPayItem:
        pay_item = XeroPayItem.objects.filter(
            name="Time and one half",
            multiplier=Decimal("1.50"),
        ).first()
        if not pay_item:
            raise CommandError(
                "XeroPayItem 'Time and one half' with multiplier=1.50 not found"
            )
        return pay_item

    @staticmethod
    def _parse_date(value: str) -> date:
        parts = value.strip().split("-")
        if len(parts) != 3:
            raise CommandError(f"Invalid date format: {value}")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))

    @staticmethod
    def _parse_decimal(value: str) -> Decimal:
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise CommandError(f"Invalid decimal value: {value}")
