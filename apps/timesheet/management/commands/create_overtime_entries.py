"""
Create missing time entries for staff to match Xero payroll hours.

Creates both overtime and ordinary-time entries to close the gap between
JM and Xero total hours. Overtime entries are created first (up to the OT
gap), then ordinary entries for any remaining headroom.

Two-step workflow:
  1. Preview: generate a CSV of proposed entries for review/editing
     python manage.py create_overtime_entries --preview

  2. Apply: read the reviewed CSV and create entries
     python manage.py create_overtime_entries --apply scripts/overtime_preview.csv

The preview CSV can be edited before applying (change job assignments,
remove rows, etc). Entries use a unique description prefix for easy
identification: "Retrospectively added overtime" / "Retrospectively added ordinary".
"""

import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from apps.accounts.models import Staff
from apps.job.models import CostLine, CostSet, Job
from apps.timesheet.services.xero_hours import (
    CUTOFF_DATE,
    LEAVE_JOB_NAMES,
    build_staff_lookup,
    get_jm_hours_for_staff_week,
    get_xero_hours_by_staff_week,
)
from apps.workflow.models import XeroPayItem

DESC_PREFIX = "Retrospectively added"

PREVIEW_CSV_PATH = (
    Path(__file__).resolve().parents[4] / "scripts" / "overtime_preview.csv"
)

PREVIEW_COLUMNS = [
    "week_start",
    "staff_name",
    "staff_id",
    "entry_type",
    "hours_to_create",
    "accounting_date",
    "job_name",
    "job_id",
    "unit_cost",
    "xero_ot",
    "jm_ot",
    "xero_total",
    "jm_total",
    "headroom",
]


class Command(BaseCommand):
    help = "Create missing overtime entries to backfill JM from Xero payroll data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--preview",
            action="store_true",
            help="Generate a CSV of proposed entries for review (step 1)",
        )
        parser.add_argument(
            "--apply",
            type=str,
            metavar="CSV_PATH",
            help="Read reviewed CSV and create entries (step 2)",
        )

    def handle(self, *args, **options):
        if options["preview"] and options["apply"]:
            raise CommandError("Use --preview OR --apply, not both")
        if not options["preview"] and not options["apply"]:
            raise CommandError(
                "Specify --preview (step 1) or --apply <csv_path> (step 2)\n"
                "  Step 1: python manage.py create_overtime_entries --preview\n"
                "  Step 2: python manage.py create_overtime_entries --apply scripts/overtime_preview.csv"
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
        primary_jobs = self._find_primary_jobs(staff_by_xero_id)
        leave_jobs = self._get_leave_jobs()
        xero_rows = get_xero_hours_by_staff_week()

        # Show primary job assignments
        self.stdout.write("\nPrimary job assignments:")
        for staff in sorted(primary_jobs, key=lambda s: s.get_display_name()):
            job_name, _, hours = primary_jobs[staff]
            self.stdout.write(
                f"  {staff.get_display_name():20s} -> {job_name} ({hours:.0f}h)"
            )

        entries = []
        skipped_matched = 0
        skipped_no_staff = 0
        skipped_no_primary_job = 0

        for row in xero_rows:
            week_start = row["week_start"]

            xero_employee_id = row["xero_employee_id"]
            if xero_employee_id not in staff_by_xero_id:
                skipped_no_staff += 1
                continue

            staff = staff_by_xero_id[xero_employee_id]

            if staff not in primary_jobs:
                skipped_no_primary_job += 1
                continue

            xero_ot_hrs = row["ot_hrs"]
            xero_ordinary_hrs = row["ordinary_hrs"]
            xero_leave_hrs = row["leave_hrs"]
            xero_leave_by_type = row.get("leave_by_type", {})
            xero_total = xero_ordinary_hrs + xero_ot_hrs + xero_leave_hrs

            jm_data = get_jm_hours_for_staff_week(str(staff.id), week_start)
            jm_total = jm_data["jm_total"]
            jm_ot = jm_data["jm_ot"]
            jm_leave_by_type = jm_data.get("jm_leave_by_type", {})

            friday = week_start + timedelta(days=4)

            headroom = xero_total - jm_total

            if headroom <= 0:
                skipped_matched += 1
                continue

            # Leave gaps first — these are specific typed entries
            leave_created = Decimal("0")
            for leave_type, xero_leave in xero_leave_by_type.items():
                jm_leave = jm_leave_by_type.get(leave_type, Decimal("0"))
                leave_gap = xero_leave - jm_leave
                # Cap at remaining headroom
                leave_to_create = max(
                    min(leave_gap, headroom - leave_created), Decimal("0")
                )
                if leave_to_create > 0:
                    leave_job = leave_jobs.get(leave_type)
                    if not leave_job:
                        continue
                    entries.append(
                        {
                            "week_start": week_start.isoformat(),
                            "staff_name": staff.get_display_name(),
                            "staff_id": str(staff.id),
                            "entry_type": f"leave:{leave_type}",
                            "hours_to_create": str(
                                leave_to_create.quantize(Decimal("0.001"))
                            ),
                            "accounting_date": friday.isoformat(),
                            "job_name": leave_type,
                            "job_id": str(leave_job.id),
                            "unit_cost": str(staff.base_wage_rate),
                            "xero_ot": str(xero_ot_hrs),
                            "jm_ot": str(jm_ot),
                            "xero_total": str(xero_total),
                            "jm_total": str(jm_total),
                            "headroom": str(headroom.quantize(Decimal("0.001"))),
                        }
                    )
                    leave_created += leave_to_create

            # OT gap (after leave)
            remaining_headroom = headroom - leave_created
            ot_gap = xero_ot_hrs - jm_ot
            ot_to_create = max(min(ot_gap, remaining_headroom), Decimal("0"))
            ordinary_to_create = max(remaining_headroom - ot_to_create, Decimal("0"))

            job_name, job_id, _ = primary_jobs[staff]

            base_row = {
                "week_start": week_start.isoformat(),
                "staff_name": staff.get_display_name(),
                "staff_id": str(staff.id),
                "accounting_date": friday.isoformat(),
                "job_name": job_name,
                "job_id": str(job_id),
                "unit_cost": str(staff.base_wage_rate),
                "xero_ot": str(xero_ot_hrs),
                "jm_ot": str(jm_ot),
                "xero_total": str(xero_total),
                "jm_total": str(jm_total),
                "headroom": str(headroom.quantize(Decimal("0.001"))),
            }

            if ot_to_create > 0:
                entries.append(
                    {
                        **base_row,
                        "entry_type": "overtime",
                        "hours_to_create": str(ot_to_create.quantize(Decimal("0.001"))),
                    }
                )

            if ordinary_to_create > 0:
                entries.append(
                    {
                        **base_row,
                        "entry_type": "ordinary",
                        "hours_to_create": str(
                            ordinary_to_create.quantize(Decimal("0.001"))
                        ),
                    }
                )

        # Report
        ot_entries = [e for e in entries if e["entry_type"] == "overtime"]
        ord_entries = [e for e in entries if e["entry_type"] == "ordinary"]
        leave_entries = [e for e in entries if e["entry_type"].startswith("leave:")]
        self.stdout.write(f"\nXero rows processed: {len(xero_rows)}")
        self.stdout.write(f"Skipped (no staff match): {skipped_no_staff}")
        self.stdout.write(f"Skipped (no primary job): {skipped_no_primary_job}")
        self.stdout.write(f"Skipped (hours matched): {skipped_matched}")
        self.stdout.write(
            f"Entries to create: {len(entries)} "
            f"({len(ot_entries)} OT, {len(ord_entries)} ordinary, "
            f"{len(leave_entries)} leave)"
        )

        if not entries:
            self.stdout.write("Nothing to create.")
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
            f"  python manage.py create_overtime_entries --apply {PREVIEW_CSV_PATH}"
        )

    # ------------------------------------------------------------------ #
    #  STEP 2: Apply
    # ------------------------------------------------------------------ #

    def _do_apply(self, csv_path: str):
        path = Path(csv_path)
        if not path.exists():
            raise CommandError(f"CSV file not found: {path}")

        ot_pay_item = self._get_ot_pay_item()
        ordinary_pay_item = self._get_ordinary_pay_item()
        leave_pay_items = self._get_leave_pay_items()

        # Read and validate all rows upfront
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise CommandError("CSV file is empty")

        self.stdout.write(f"Read {len(rows)} entries from {path}")

        # Pre-fetch all referenced staff and cost sets
        staff_cache = {}
        cost_set_cache = {}

        validated = []
        for i, row in enumerate(rows, 1):
            staff_id = row["staff_id"].strip()
            job_id = row["job_id"].strip()
            staff_name = row["staff_name"]
            entry_type = row["entry_type"].strip()

            is_leave = entry_type.startswith("leave:")
            if entry_type not in ("overtime", "ordinary") and not is_leave:
                raise CommandError(
                    f"Row {i}: entry_type must be 'overtime', 'ordinary', "
                    f"or 'leave:<type>', got '{entry_type}'"
                )

            if is_leave:
                leave_type = entry_type.split(":", 1)[1]
                if leave_type not in leave_pay_items:
                    raise CommandError(
                        f"Row {i}: no pay item found for leave type '{leave_type}'"
                    )

            if staff_id not in staff_cache:
                try:
                    staff_cache[staff_id] = Staff.objects.get(id=staff_id)
                except Staff.DoesNotExist:
                    raise CommandError(f"Row {i}: Staff not found: {staff_id}")

            if job_id not in cost_set_cache:
                try:
                    cost_set_cache[job_id] = CostSet.objects.get(
                        job_id=job_id, kind="actual"
                    )
                except CostSet.DoesNotExist:
                    raise CommandError(
                        f"Row {i}: No 'actual' CostSet for job {job_id} "
                        f"({row.get('job_name', '?')})"
                    )

            staff = staff_cache[staff_id]
            cost_set = cost_set_cache[job_id]
            hours = Decimal(row["hours_to_create"])
            accounting_date = self._parse_date(row["accounting_date"])
            unit_cost = Decimal(row["unit_cost"])

            if hours <= 0:
                raise CommandError(
                    f"Row {i}: hours_to_create must be positive, got {hours}"
                )

            validated.append(
                {
                    "staff": staff,
                    "staff_name": staff_name,
                    "cost_set": cost_set,
                    "job_name": row.get("job_name", "?"),
                    "entry_type": entry_type,
                    "hours": hours,
                    "accounting_date": accounting_date,
                    "unit_cost": unit_cost,
                    "week_start": row["week_start"],
                }
            )

        self.stdout.write(f"Validated {len(validated)} entries.\n")

        # Create
        counts = {"overtime": 0, "ordinary": 0, "leave": 0}
        with transaction.atomic():
            for entry in validated:
                staff = entry["staff"]
                entry_type = entry["entry_type"]

                if entry_type == "overtime":
                    pay_item = ot_pay_item
                    multiplier = 1.5
                    label = "OT"
                elif entry_type == "ordinary":
                    pay_item = ordinary_pay_item
                    multiplier = 1.0
                    label = "ordinary"
                else:
                    leave_type = entry_type.split(":", 1)[1]
                    pay_item = leave_pay_items[leave_type]
                    multiplier = float(pay_item.multiplier or 0)
                    label = leave_type

                cl = CostLine.objects.create(
                    cost_set=entry["cost_set"],
                    kind="time",
                    desc=f"{DESC_PREFIX} {label} - {entry['staff_name']}",
                    quantity=entry["hours"],
                    unit_cost=entry["unit_cost"],
                    unit_rev=Decimal("0"),
                    accounting_date=entry["accounting_date"],
                    xero_pay_item=pay_item,
                    meta={
                        "staff_id": str(staff.id),
                        "date": entry["accounting_date"].isoformat(),
                        "is_billable": False,
                        "created_from_timesheet": True,
                        "wage_rate_multiplier": multiplier,
                    },
                )
                count_key = "leave" if entry_type.startswith("leave:") else entry_type
                counts[count_key] += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created: {entry['week_start']} | "
                        f"{entry['staff_name']} | "
                        f"{entry['hours']}h {label} | "
                        f"${cl.total_cost} | "
                        f"job: {entry['job_name']} | ID: {cl.id}"
                    )
                )

        total = sum(counts.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {counts['overtime']} OT + "
                f"{counts['ordinary']} ordinary + {counts['leave']} leave "
                f"= {total} total entries."
            )
        )

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

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

    def _get_ordinary_pay_item(self) -> XeroPayItem:
        pay_item = XeroPayItem.objects.filter(
            name="Ordinary Time",
            multiplier=Decimal("1.00"),
        ).first()
        if not pay_item:
            raise CommandError(
                "XeroPayItem 'Ordinary Time' with multiplier=1.00 not found"
            )
        return pay_item

    def _get_leave_pay_items(self) -> dict[str, XeroPayItem]:
        """Return dict mapping leave job name -> XeroPayItem for leave types."""
        result = {}
        for name in LEAVE_JOB_NAMES:
            pay_item = XeroPayItem.objects.filter(
                name=name, uses_leave_api=True
            ).first()
            if pay_item:
                result[name] = pay_item
        return result

    def _get_leave_jobs(self) -> dict[str, Job]:
        """Return dict mapping leave job name -> Job for leave types."""
        result = {}
        for job in Job.objects.filter(status="special", name__in=LEAVE_JOB_NAMES):
            result[job.name] = job
        return result

    def _find_primary_jobs(self, staff_by_xero_id: dict[str, Staff]) -> dict:
        """For each staff, find the non-leave special job with most hours.

        Returns dict of Staff -> (job_name, job_id, total_hours).
        """
        result = {}
        for staff in staff_by_xero_id.values():
            if staff in result:
                continue

            top_job = (
                CostLine.objects.filter(
                    kind="time",
                    cost_set__kind="actual",
                    cost_set__job__status="special",
                    accounting_date__gte=CUTOFF_DATE,
                    meta__staff_id=str(staff.id),
                )
                .exclude(cost_set__job__name__in=LEAVE_JOB_NAMES)
                .values("cost_set__job__id", "cost_set__job__name")
                .annotate(total_hrs=Sum("quantity"))
                .order_by("-total_hrs")
                .first()
            )
            if not top_job:
                self.stderr.write(
                    self.style.WARNING(
                        f"  {staff.get_display_name()}: no non-leave special job found, skipping"
                    )
                )
                continue

            result[staff] = (
                top_job["cost_set__job__name"],
                top_job["cost_set__job__id"],
                float(top_job["total_hrs"]),
            )

        return result

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
