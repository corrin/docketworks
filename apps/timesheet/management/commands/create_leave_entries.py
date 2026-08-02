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
from django.db import transaction

from apps.accounts.models import Staff
from apps.job.models import CostLine, CostSet, Job
from apps.workflow.services.error_persistence import persist_app_error

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


def build_leave_cost_line(
    staff: Staff,
    cost_set: CostSet,
    job: Job,
    leave_type: str,
    entry_date: date,
    hours: Decimal,
) -> CostLine:
    """Build — but not save — one leave CostLine.

    Full model validation runs inside CostLine.save() (which also assigns
    entry_seq, so it cannot run earlier); the guard here exists to give the
    operator a named-staff error instead of a ValidationError dump.
    """
    if staff.default_labour_subtype is None:
        raise CommandError(
            f"Staff '{staff.get_display_full_name()}' has no "
            "default_labour_subtype set"
        )
    label = LEAVE_JOB_NAMES[leave_type]
    wage = Decimal("0") if leave_type == "unpaid" else staff.base_wage_rate
    cost_line = CostLine(
        cost_set=cost_set,
        kind="time",
        desc=f"{label} - {staff.get_display_name()}",
        quantity=hours,
        unit_cost=wage,
        unit_rev=Decimal("0"),
        accounting_date=entry_date,
        staff=staff,
        xero_pay_item=job.default_xero_pay_item,
        labour_subtype=staff.default_labour_subtype,
        meta={
            "staff_id": str(staff.id),
            "date": entry_date.isoformat(),
            "is_billable": False,
            "created_from_timesheet": True,
            "wage_rate_multiplier": 1,
        },
    )
    return cost_line


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
            except Job.DoesNotExist as exc:
                persist_app_error(exc)
                raise CommandError(
                    f"Leave job '{job_name}' not found with status='special'"
                ) from exc
            if not job.default_xero_pay_item:
                raise CommandError(
                    f"Leave job '{job_name}' has no default_xero_pay_item set"
                )
            leave_jobs[key] = job
            try:
                leave_cost_sets[key] = CostSet.objects.get(job_id=job.id, kind="actual")
            except CostSet.DoesNotExist as exc:
                persist_app_error(exc)
                raise CommandError(
                    f"No 'actual' CostSet found for job '{job_name}'"
                ) from exc

        if not ENTRIES:
            self.stdout.write("No entries to create. Edit ENTRIES in the command file.")
            return

        # --- Validate all entries upfront ---
        validated: list[CostLine] = []
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
                staff=staff,
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
                staff=staff,
            )
            other_hours = sum(float(cl.quantity) for cl in other_entries)
            if other_hours + float(hours) > 24:
                raise CommandError(
                    f"{staff_name} on {entry_date}: adding {hours}h leave to "
                    f"existing {other_hours}h would exceed 24h"
                )

            validated.append(
                build_leave_cost_line(
                    staff,
                    cost_set,
                    leave_jobs[leave_type],
                    leave_type,
                    entry_date,
                    hours,
                )
            )

        self.stdout.write(f"Validated {len(validated)} entries.")

        # --- Create entries; a dry run saves them for real (exercising every
        # model rule, entry_seq assignment, and DB constraint) then rolls the
        # whole transaction back, so it can never report success for entries
        # that would fail a live run. ---
        with transaction.atomic():
            for cost_line in validated:
                cost_line.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created: {cost_line.accounting_date} "
                        f"({cost_line.accounting_date.strftime('%a')}) | "
                        f"{cost_line.desc} | {cost_line.quantity}h | "
                        f"${cost_line.total_cost} | ID: {cost_line.id}"
                    )
                )
            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(
                    self.style.WARNING(
                        f"DRY RUN - all {len(validated)} entries rolled back."
                    )
                )
                return

        self.stdout.write(
            self.style.SUCCESS(f"Done. Created {len(validated)} entries.")
        )
