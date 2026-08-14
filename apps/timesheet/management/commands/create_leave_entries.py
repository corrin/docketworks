"""Create missing leave entries for staff who didn't log leave locally.

Xero is the system of record for payroll. This command backfills local leave
CostLines to match what Xero shows, so management reporting is accurate.

Usage:
    python manage.py create_leave_entries --dry-run
    python manage.py create_leave_entries
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Sum

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet

from ._repair_shared import build_repair_time_line

# --- Entry batches ---
# IMPORTANT: NEVER edit or remove existing batches. Only APPEND new ones.
# Duplicates are safely skipped at runtime, which is what makes re-running the
# command with historical batches present a no-op rather than a double-write.
# Each row is staff first name, date, leave type, hours.
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

ENTRIES: list[tuple[str, date, str, Decimal]] = (
    _batch_20260324 + _batch_20260326a + _batch_20260326b + _batch_20260326c
)

LEAVE_JOB_NAMES = {
    "annual": "Annual Leave",
    "bereavement": "Bereavement Leave",
    "sick": "Sick Leave",
    "unpaid": "Unpaid Leave",
}

MAX_DAY_HOURS = Decimal("24")

# date.weekday() numbers Monday 0 .. Sunday 6.
SATURDAY = 5


class Command(BaseCommand):
    """Backfill leave CostLines from the append-only ENTRIES batches above."""

    help = "Create missing leave entries to backfill local data from Xero payroll"

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the dry-run flag."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and show what would be created without writing to DB",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Validate every entry upfront, then create the missing ones atomically."""
        dry_run = options.get("dry_run")
        if not isinstance(dry_run, bool):
            raise TypeError("The dry-run option must be a boolean")

        leave_jobs, leave_cost_sets = self._load_leave_jobs()

        if not ENTRIES:
            self.stdout.write("No entries to create. Edit ENTRIES in the command file.")
            return

        validated: list[CostLine] = []
        for staff_name, entry_date, leave_type, hours in ENTRIES:
            cost_line = self._validate_entry(
                staff_name,
                entry_date,
                leave_type,
                hours,
                leave_jobs=leave_jobs,
                leave_cost_sets=leave_cost_sets,
            )
            if cost_line is not None:
                validated.append(cost_line)

        self.stdout.write(f"Validated {len(validated)} entries.")

        # A dry run saves the entries for real (exercising every model rule,
        # entry_seq assignment, and DB constraint) then rolls the whole
        # transaction back, so it can never report success for entries that
        # would fail a live run.
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
                    self.style.WARNING(f"DRY RUN - all {len(validated)} entries rolled back.")
                )
                return

        self.stdout.write(self.style.SUCCESS(f"Done. Created {len(validated)} entries."))

    def _load_leave_jobs(self) -> tuple[dict[str, Job], dict[str, CostSet]]:
        """Resolve the special leave jobs and their actual cost sets, or refuse."""
        leave_jobs: dict[str, Job] = {}
        leave_cost_sets: dict[str, CostSet] = {}
        for key, job_name in LEAVE_JOB_NAMES.items():
            try:
                job = Job.objects.get(name=job_name, status="special")
            except Job.DoesNotExist as exc:
                raise CommandError(
                    f"Leave job '{job_name}' not found with status='special'"
                ) from exc
            if job.default_xero_pay_item_id is None:
                raise CommandError(f"Leave job '{job_name}' has no default_xero_pay_item set")
            if job.latest_actual is None:
                raise CommandError(f"No 'actual' CostSet found for job '{job_name}'")
            leave_jobs[key] = job
            leave_cost_sets[key] = job.latest_actual
        return leave_jobs, leave_cost_sets

    def _validate_entry(  # noqa: PLR0913 -- one batch row plus the two resolved lookups
        self,
        staff_name: str,
        entry_date: date,
        leave_type: str,
        hours: Decimal,
        *,
        leave_jobs: dict[str, Job],
        leave_cost_sets: dict[str, CostSet],
    ) -> CostLine | None:
        """Validate one batch row; None means it already exists and is skipped."""
        if leave_type not in leave_cost_sets:
            raise CommandError(
                f"Unknown leave type '{leave_type}'. Valid: {sorted(leave_cost_sets)}"
            )
        if hours <= 0:
            raise CommandError(
                f"Hours must be positive, got {hours} for {staff_name} on {entry_date}"
            )
        if entry_date.weekday() >= SATURDAY:
            raise CommandError(f"{entry_date} is a weekend ({entry_date.strftime('%A')})")

        staff = self._resolve_staff(staff_name)
        if leave_type != "unpaid" and not staff.base_wage_rate:
            raise CommandError(f"Staff '{staff_name}' has no base_wage_rate set")

        cost_set = leave_cost_sets[leave_type]
        job = leave_jobs[leave_type]

        already_exists = CostLine.objects.filter(
            cost_set=cost_set,
            kind="time",
            accounting_date=entry_date,
            staff=staff,
        ).exists()
        if already_exists:
            self.stdout.write(
                f"  Skipping (already exists): {entry_date} | {staff_name} | {leave_type}"
            )
            return None

        other_hours = CostLine.objects.filter(
            kind="time",
            cost_set__kind="actual",
            accounting_date=entry_date,
            staff=staff,
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        if other_hours + hours > MAX_DAY_HOURS:
            raise CommandError(
                f"{staff_name} on {entry_date}: adding {hours}h leave to "
                f"existing {other_hours}h would exceed 24h"
            )

        wage = Decimal("0") if leave_type == "unpaid" else staff.base_wage_rate
        label = LEAVE_JOB_NAMES[leave_type]
        return build_repair_time_line(
            staff,
            cost_set,
            desc=f"{label} - {staff.get_display_name()}",
            hours=hours,
            unit_cost=wage,
            accounting_date=entry_date,
            pay_item_id=job.default_xero_pay_item_id,
            wage_rate_multiplier=1.0,
        )

    @staticmethod
    def _resolve_staff(staff_name: str) -> Staff:
        """Resolve a batch row's first name to exactly one staff member."""
        matches = list(Staff.objects.filter(first_name=staff_name))
        if len(matches) == 0:
            raise CommandError(f"No staff found with first_name='{staff_name}'")
        if len(matches) > 1:
            raise CommandError(
                f"Multiple staff match first_name='{staff_name}': "
                f"{[(s.first_name, s.last_name) for s in matches]}"
            )
        return matches[0]
