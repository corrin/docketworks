"""
Create missing leave entries for staff who didn't log leave in JM.

Xero is SOR for payroll. This command backfills JM with leave entries
to match what Xero shows, so management reporting is accurate.

Usage:
    python manage.py create_leave_entries --dry-run
    python manage.py create_leave_entries
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Staff
from apps.job.models import CostLine, CostSet, Job

# --- Entry batches ---
# IMPORTANT: NEVER edit or remove existing batches. Only APPEND new ones.
# Duplicates are safely skipped at runtime.
# Format: (staff_first_name, date, leave_type, hours)
# Valid leave types: annual, bereavement, sick, unpaid

# 2026-03-24: Backfill leave from Xero payroll — Richard and Michael missed days
_batch_20260324 = [
    ("Richard John", date(2026, 2, 16), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 2, 19), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 2, 20), "annual", Decimal("8.000")),
    ("Michael (Peng)", date(2026, 3, 16), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 3, 16), "annual", Decimal("8.000")),
    ("Akleshwar Sen", date(2026, 3, 17), "sick", Decimal("8.000")),
]

# 2026-03-26: Cindy sick leave w/c Mar 23 (Mon 7h + 1h office admin logged separately)
_batch_20260326a = [
    ("Cindy", date(2026, 3, 23), "sick", Decimal("7.000")),
    ("Cindy", date(2026, 3, 24), "sick", Decimal("8.000")),
    ("Cindy", date(2026, 3, 25), "sick", Decimal("8.000")),
]

# 2026-03-26: Richard, Aaron, Michael — annual leave full week Mar 23-27
_batch_20260326b = [
    ("Richard John", date(2026, 3, 23), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 3, 24), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 3, 25), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 3, 26), "annual", Decimal("8.000")),
    ("Richard John", date(2026, 3, 27), "annual", Decimal("8.000")),
    ("Aaron Christopher", date(2026, 3, 23), "annual", Decimal("8.000")),
    ("Aaron Christopher", date(2026, 3, 24), "annual", Decimal("8.000")),
    ("Aaron Christopher", date(2026, 3, 25), "annual", Decimal("8.000")),
    ("Aaron Christopher", date(2026, 3, 26), "annual", Decimal("8.000")),
    ("Aaron Christopher", date(2026, 3, 27), "annual", Decimal("8.000")),
    ("Michael (Peng)", date(2026, 3, 23), "annual", Decimal("8.000")),
    ("Michael (Peng)", date(2026, 3, 24), "annual", Decimal("8.000")),
    ("Michael (Peng)", date(2026, 3, 25), "annual", Decimal("8.000")),
    ("Michael (Peng)", date(2026, 3, 26), "annual", Decimal("8.000")),
    ("Michael (Peng)", date(2026, 3, 27), "annual", Decimal("8.000")),
]

# 2026-03-26: Ben Kek unpaid leave backfill — Feb 16 to Mar 27
# His entries stopped at Feb 13; he's still on unpaid leave.
_batch_20260326c = [
    ("Ben", date(2026, 2, 16), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 17), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 18), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 19), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 20), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 23), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 24), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 25), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 26), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 2, 27), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 2), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 3), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 4), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 5), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 6), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 9), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 10), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 11), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 12), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 13), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 16), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 17), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 18), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 19), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 20), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 23), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 24), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 25), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 26), "unpaid", Decimal("8.000")),
    ("Ben", date(2026, 3, 27), "unpaid", Decimal("8.000")),
]

ENTRIES = _batch_20260324 + _batch_20260326a + _batch_20260326b + _batch_20260326c

LEAVE_JOB_NAMES = {
    "annual": "Annual Leave",
    "bereavement": "Bereavement Leave",
    "sick": "Sick Leave",
    "unpaid": "Unpaid Leave",
}


class Command(BaseCommand):
    help = "Create missing leave entries to backfill JM from Xero payroll data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and show what would be created without writing to DB",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # --- Look up leave jobs by name ---
        leave_jobs = {}
        leave_cost_sets = {}
        for key, job_name in LEAVE_JOB_NAMES.items():
            try:
                job = Job.objects.get(name=job_name, status="special")
            except Job.DoesNotExist:
                raise CommandError(
                    f"Leave job '{job_name}' not found with status='special'"
                )
            if not job.default_xero_pay_item:
                raise CommandError(
                    f"Leave job '{job_name}' has no default_xero_pay_item set"
                )
            leave_jobs[key] = job
            try:
                leave_cost_sets[key] = CostSet.objects.get(job_id=job.id, kind="actual")
            except CostSet.DoesNotExist:
                raise CommandError(f"No 'actual' CostSet found for job '{job_name}'")

        if not ENTRIES:
            self.stdout.write("No entries to create. Edit ENTRIES in the command file.")
            return

        # --- Validate all entries upfront ---
        validated = []
        for staff_name, entry_date, leave_type, hours in ENTRIES:
            if leave_type not in leave_cost_sets:
                raise CommandError(
                    f"Unknown leave type '{leave_type}'. "
                    f"Valid: {list(leave_cost_sets)}"
                )

            if hours <= 0:
                raise CommandError(
                    f"Hours must be positive, got {hours} for "
                    f"{staff_name} on {entry_date}"
                )

            if entry_date.weekday() >= 5:
                raise CommandError(
                    f"{entry_date} is a weekend ({entry_date.strftime('%A')})"
                )

            matches = Staff.objects.filter(first_name=staff_name)
            if matches.count() == 0:
                raise CommandError(f"No staff found with first_name='{staff_name}'")
            if matches.count() > 1:
                raise CommandError(
                    f"Multiple staff match first_name='{staff_name}': "
                    f"{[(s.first_name, s.last_name) for s in matches]}"
                )
            staff = matches.get()

            if leave_type != "unpaid" and not staff.base_wage_rate:
                raise CommandError(f"Staff '{staff_name}' has no base_wage_rate set")

            cost_set = leave_cost_sets[leave_type]

            # Check for duplicate leave entry — skip if already applied
            existing = CostLine.objects.filter(
                cost_set=cost_set,
                kind="time",
                accounting_date=entry_date,
                meta__staff_id=str(staff.id),
            ).exists()
            if existing:
                self.stdout.write(
                    f"  Skipping (already exists): {entry_date} | "
                    f"{staff_name} | {leave_type}"
                )
                continue

            # Check total hours won't exceed 24
            other_entries = CostLine.objects.filter(
                kind="time",
                cost_set__kind="actual",
                accounting_date=entry_date,
                meta__contains=str(staff.id),
            )
            other_hours = sum(float(cl.quantity) for cl in other_entries)
            if other_hours + float(hours) > 24:
                raise CommandError(
                    f"{staff_name} on {entry_date}: adding {hours}h leave to "
                    f"existing {other_hours}h would exceed 24h"
                )

            validated.append(
                (staff, entry_date, leave_type, hours, cost_set, leave_jobs[leave_type])
            )

        self.stdout.write(f"Validated {len(validated)} entries.")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes made:"))
            for staff, entry_date, leave_type, hours, _, _ in validated:
                label = LEAVE_JOB_NAMES[leave_type]
                wage = Decimal("0") if leave_type == "unpaid" else staff.base_wage_rate
                cost = wage * hours
                self.stdout.write(
                    f"  {entry_date} ({entry_date.strftime('%a')}) | "
                    f"{staff.get_display_name()} | {label} | "
                    f"{hours}h | ${cost}"
                )
            return

        # --- Create entries (all validation passed) ---
        for staff, entry_date, leave_type, hours, cost_set, job in validated:
            label = LEAVE_JOB_NAMES[leave_type]

            wage = Decimal("0") if leave_type == "unpaid" else staff.base_wage_rate

            cl = CostLine.objects.create(
                cost_set=cost_set,
                kind="time",
                desc=f"{label} - {staff.get_display_name()}",
                quantity=hours,
                unit_cost=wage,
                unit_rev=Decimal("0"),
                accounting_date=entry_date,
                xero_pay_item=job.default_xero_pay_item,
                meta={
                    "staff_id": str(staff.id),
                    "date": entry_date.isoformat(),
                    "is_billable": False,
                    "created_from_timesheet": True,
                    "wage_rate_multiplier": 1,
                },
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created: {entry_date} ({entry_date.strftime('%a')}) | "
                    f"{staff.get_display_name()} | {label} | {hours}h | "
                    f"${cl.total_cost} | ID: {cl.id}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done. Created {len(validated)} entries.")
        )
