"""Create missing time entries for staff to match Xero payroll hours.

Creates both overtime and ordinary-time entries to close the gap between the
local records and Xero total hours. Leave gaps fill first (typed entries),
then overtime up to the overtime headroom, then ordinary time for whatever
headroom remains.

Two-step workflow:
  1. Preview: generate a CSV of proposed entries for review/editing
     python manage.py create_overtime_entries --preview

  2. Apply: read the reviewed CSV and create entries, approved as Xero paid them
     python manage.py create_overtime_entries --apply scripts/overtime_preview.csv \
         --actor <office staff email>

The preview CSV can be edited before applying (change job assignments, dates,
remove rows, etc). Entries use a unique description prefix for easy
identification: "Retrospectively added OT" / "Retrospectively added ordinary".
The entry writer prices each one at the worker's wage times its rate.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Sum

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.time_entry_rates import (
    DEFAULT_MULTIPLIER,
    OVERTIME_MULTIPLIER,
    rate_from_meta,
)
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopEntryCreateData,
    create_entry,
)
from apps.timesheet.services.xero_hours import (
    CUTOFF_DATE,
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
    parse_date,
    parse_decimal,
    read_reviewed_csv,
    resolve_actor,
    resolve_preview_or_apply,
    write_preview_csv,
    written_entries,
)

DESC_PREFIX = "Retrospectively added"

PREVIEW_CSV_PATH = Path(__file__).resolve().parents[4] / "scripts" / "overtime_preview.csv"

PREVIEW_COLUMNS = [
    "week_start",
    "staff_name",
    "staff_id",
    "entry_type",
    "hours_to_create",
    "accounting_date",
    "job_name",
    "job_id",
    "xero_ot",
    "jm_ot",
    "xero_total",
    "jm_total",
    "headroom",
]

# The Friday of the target week carries every synthetic entry: the true day is
# unknowable from payroll totals, and Friday keeps the entry inside the week.
FRIDAY_OFFSET_DAYS = 4

THREE_DP = Decimal("0.001")


@dataclass(frozen=True)
class _PrimaryJob:
    """The non-leave special job a staff member's synthetic hours default to."""

    job_name: str
    job_id: UUID
    total_hours: float


class _ValidatedEntry(TypedDict):
    """One CSV row, validated, awaiting the atomic write."""

    staff: Staff
    data: WorkshopEntryCreateData
    staff_name: str
    job_name: str
    entry_type: str
    label: str
    week_start: str


class Command(BaseCommand):
    """Two-step (preview CSV, then apply) backfill of missing OT/ordinary hours."""

    help = "Create missing overtime entries to backfill local data from Xero payroll"

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the two workflow steps."""
        add_preview_apply_arguments(parser)
        add_actor_argument(parser)

    def handle(self, *_args: object, **options: object) -> None:
        """Dispatch to the preview or apply step."""
        apply_path = resolve_preview_or_apply(
            options,
            command="create_overtime_entries",
            default_csv="scripts/overtime_preview.csv",
        )
        if apply_path is None:
            self._do_preview()
        else:
            self._do_apply(apply_path, resolve_actor(options))

    # ------------------------------------------------------------------ #
    #  STEP 1: Preview
    # ------------------------------------------------------------------ #

    def _do_preview(self) -> None:
        """Compare Xero and local hours per staff-week and write the proposal CSV."""
        staff_by_xero_id = build_staff_lookup()
        primary_jobs = self._find_primary_jobs(staff_by_xero_id)
        leave_jobs = self._get_leave_jobs()
        xero_rows = get_xero_hours_by_staff_week()

        self.stdout.write("\nPrimary job assignments:")
        for assigned_staff in sorted(primary_jobs, key=lambda s: s.get_display_name()):
            primary = primary_jobs[assigned_staff]
            self.stdout.write(
                f"  {assigned_staff.get_display_name():20s} -> "
                f"{primary.job_name} ({primary.total_hours:.0f}h)"
            )

        entries: list[dict[str, str]] = []
        skipped_matched = 0
        skipped_no_staff = 0
        skipped_no_primary_job = 0

        for row in xero_rows:
            staff = staff_by_xero_id.get(row["xero_employee_id"])
            if staff is None:
                skipped_no_staff += 1
                continue
            if staff not in primary_jobs:
                skipped_no_primary_job += 1
                continue
            week_entries = self._preview_rows_for_week(row, staff, primary_jobs[staff], leave_jobs)
            if week_entries is None:
                skipped_matched += 1
                continue
            entries.extend(week_entries)

        self._report_and_write_preview(
            entries,
            xero_rows_processed=len(xero_rows),
            skipped_no_staff=skipped_no_staff,
            skipped_no_primary_job=skipped_no_primary_job,
            skipped_matched=skipped_matched,
        )

    def _preview_rows_for_week(
        self,
        row: XeroWeekRow,
        staff: Staff,
        primary: _PrimaryJob,
        leave_jobs: dict[str, Job],
    ) -> list[dict[str, str]] | None:
        """Propose entries for one staff-week; None means the hours already match."""
        week_start = row["week_start"]
        xero_total = row["ordinary_hrs"] + row["ot_hrs"] + row["leave_hrs"]

        jm_data = get_jm_hours_for_staff_week(str(staff.id), week_start)
        headroom = xero_total - jm_data["jm_total"]
        if headroom <= 0:
            return None

        friday = week_start + timedelta(days=FRIDAY_OFFSET_DAYS)
        base_row = {
            "week_start": week_start.isoformat(),
            "staff_name": staff.get_display_name(),
            "staff_id": str(staff.id),
            "accounting_date": friday.isoformat(),
            "xero_ot": str(row["ot_hrs"]),
            "jm_ot": str(jm_data["jm_ot"]),
            "xero_total": str(xero_total),
            "jm_total": str(jm_data["jm_total"]),
            "headroom": str(headroom.quantize(THREE_DP)),
        }

        week_entries: list[dict[str, str]] = []

        # Leave gaps first — these are specific typed entries.
        leave_created = Decimal("0")
        for leave_type, xero_leave in row["leave_by_type"].items():
            jm_leave = jm_data["jm_leave_by_type"].get(leave_type, Decimal("0"))
            leave_gap = xero_leave - jm_leave
            leave_to_create = max(min(leave_gap, headroom - leave_created), Decimal("0"))
            if leave_to_create <= 0:
                continue
            leave_job = leave_jobs.get(leave_type)
            if leave_job is None:
                continue
            week_entries.append(
                {
                    **base_row,
                    "entry_type": f"leave:{leave_type}",
                    "hours_to_create": str(leave_to_create.quantize(THREE_DP)),
                    "job_name": leave_type,
                    "job_id": str(leave_job.id),
                }
            )
            leave_created += leave_to_create

        # OT gap next (after leave), ordinary time for the rest.
        remaining_headroom = headroom - leave_created
        ot_gap = row["ot_hrs"] - jm_data["jm_ot"]
        ot_to_create = max(min(ot_gap, remaining_headroom), Decimal("0"))
        ordinary_to_create = max(remaining_headroom - ot_to_create, Decimal("0"))

        for entry_type, hours in (("overtime", ot_to_create), ("ordinary", ordinary_to_create)):
            if hours <= 0:
                continue
            week_entries.append(
                {
                    **base_row,
                    "entry_type": entry_type,
                    "hours_to_create": str(hours.quantize(THREE_DP)),
                    "job_name": primary.job_name,
                    "job_id": str(primary.job_id),
                }
            )
        return week_entries

    def _report_and_write_preview(
        self,
        entries: list[dict[str, str]],
        *,
        xero_rows_processed: int,
        skipped_no_staff: int,
        skipped_no_primary_job: int,
        skipped_matched: int,
    ) -> None:
        """Summarise the proposal and write the review CSV."""
        ot_entries = [e for e in entries if e["entry_type"] == "overtime"]
        ord_entries = [e for e in entries if e["entry_type"] == "ordinary"]
        leave_entries = [e for e in entries if e["entry_type"].startswith("leave:")]
        self.stdout.write(f"\nXero rows processed: {xero_rows_processed}")
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

        write_preview_csv(PREVIEW_CSV_PATH, PREVIEW_COLUMNS, entries)

        self.stdout.write(self.style.SUCCESS(f"\nPreview written to: {PREVIEW_CSV_PATH}"))
        self.stdout.write(
            "Review/edit the CSV, then run:\n"
            f"  python manage.py create_overtime_entries --apply {PREVIEW_CSV_PATH} "
            "--actor <office staff email>"
        )

    # ------------------------------------------------------------------ #
    #  STEP 2: Apply
    # ------------------------------------------------------------------ #

    def _do_apply(self, csv_path: str, actor: Staff) -> None:
        """Create the entries a reviewed CSV describes, all-or-nothing."""
        path, rows = read_reviewed_csv(csv_path, PREVIEW_COLUMNS)
        self.stdout.write(f"Read {len(rows)} entries from {path}")

        validated = self._validate_rows(rows)
        self.stdout.write(f"Validated {len(validated)} entries.\n")

        counts = {"overtime": 0, "ordinary": 0, "leave": 0}
        with transaction.atomic():
            for i, entry in enumerate(validated, 1):
                staff, day = entry["staff"], entry["data"]["accounting_date"]
                untouched = day_line_ids(staff, day)
                create_entry(actor, staff, entry["data"])
                written = written_entries(staff, day, untouched)
                if entry["entry_type"] == "ordinary" and any(
                    rate_from_meta(line.meta, "wage_rate_multiplier") != DEFAULT_MULTIPLIER
                    for line in written
                ):
                    # Xero paid these hours as ordinary time; on a day already
                    # past the usual hours the writer puts them at overtime.
                    raise CommandError(
                        f"Row {i}: {day} is already past {entry['staff_name']}'s usual "
                        "day, so these hours would go at overtime. Move the row to a "
                        "day with room and apply again."
                    )
                approve_written(actor, staff, day, untouched)
                count_key = (
                    "leave" if entry["entry_type"].startswith("leave:") else entry["entry_type"]
                )
                counts[count_key] += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created: {entry['week_start']} | "
                        f"{entry['staff_name']} | "
                        f"{entry['data']['hours']}h {entry['label']} | "
                        f"${sum(line.total_cost for line in written)} | "
                        f"job: {entry['job_name']} | "
                        f"ID: {', '.join(str(line.id) for line in written)}"
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

    def _validate_rows(self, rows: list[dict[str, str]]) -> list[_ValidatedEntry]:
        """Validate every CSV row upfront, before anything is written."""
        leave_jobs = self._get_leave_jobs()
        staff_cache: dict[str, Staff] = {}
        job_cache: dict[str, Job] = {}

        validated: list[_ValidatedEntry] = []
        for i, row in enumerate(rows, 1):
            entry_type = row["entry_type"].strip()
            is_leave = entry_type.startswith("leave:")
            if entry_type not in ("overtime", "ordinary") and not is_leave:
                raise CommandError(
                    f"Row {i}: entry_type must be 'overtime', 'ordinary', "
                    f"or 'leave:<type>', got '{entry_type}'"
                )

            staff = self._cached_staff(staff_cache, row["staff_id"].strip(), row_number=i)
            job = self._cached_job(job_cache, row["job_id"].strip(), row_number=i)

            hours = parse_decimal(row["hours_to_create"])
            if hours <= 0:
                raise CommandError(f"Row {i}: hours_to_create must be positive, got {hours}")

            data: WorkshopEntryCreateData = {
                "job_id": job.id,
                "accounting_date": parse_date(row["accounting_date"]),
                "hours": hours,
                # Payroll-backfill work is never billable.
                "is_billable": False,
            }
            if entry_type == "overtime":
                data["wage_rate_multiplier"] = OVERTIME_MULTIPLIER
                label = "OT"
            elif entry_type == "ordinary":
                data["wage_rate_multiplier"] = DEFAULT_MULTIPLIER
                label = "ordinary"
            else:
                # The leave job prices its own hours (time_entry_rates).
                label = entry_type.split(":", 1)[1]
                if leave_jobs.get(label) != job:
                    raise CommandError(
                        f"Row {i}: job {job.name} is not the job for leave '{label}'"
                    )
            data["description"] = f"{DESC_PREFIX} {label} - {row['staff_name']}"
            validated.append(
                _ValidatedEntry(
                    staff=staff,
                    data=data,
                    staff_name=row["staff_name"],
                    job_name=row.get("job_name", "?"),
                    entry_type=entry_type,
                    label=label,
                    week_start=row["week_start"],
                )
            )
        return validated

    @staticmethod
    def _cached_staff(cache: dict[str, Staff], staff_id: str, *, row_number: int) -> Staff:
        """Resolve a CSV staff id through the per-run cache."""
        if staff_id not in cache:
            try:
                cache[staff_id] = Staff.objects.get(id=staff_id)
            except Staff.DoesNotExist as exc:
                raise CommandError(f"Row {row_number}: Staff not found: {staff_id}") from exc
        return cache[staff_id]

    @staticmethod
    def _cached_job(cache: dict[str, Job], job_id: str, *, row_number: int) -> Job:
        """Resolve a CSV job id through the per-run cache."""
        if job_id not in cache:
            try:
                cache[job_id] = Job.objects.get(id=job_id)
            except Job.DoesNotExist as exc:
                raise CommandError(f"Row {row_number}: Job not found: {job_id}") from exc
        return cache[job_id]

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_leave_jobs() -> dict[str, Job]:
        """Return leave category CODE -> Job for the configured leave jobs.

        Opus: Keyed by code so it joins the Xero side, which `_extract_leave_type`
        also resolves to a code. Keying one by job name and the other by
        anything else is how the two halves of a comparison silently stop
        matching — every leave line would then read as a gap and be recreated.
        """
        from apps.timesheet.models import LeaveType  # noqa: PLC0415

        return {
            leave_type.code: leave_type.job
            for leave_type in LeaveType.objects.exclude(job=None).select_related("job")
            if leave_type.job is not None
        }

    def _find_primary_jobs(self, staff_by_xero_id: dict[str, Staff]) -> dict[Staff, _PrimaryJob]:
        """For each staff member, find the non-leave special job with most hours."""
        result: dict[Staff, _PrimaryJob] = {}
        for staff in staff_by_xero_id.values():
            if staff in result:
                continue
            top_job = (
                CostLine.objects.filter(
                    kind="time",
                    cost_set__kind="actual",
                    cost_set__job__status="special",
                    accounting_date__gte=CUTOFF_DATE,
                    staff=staff,
                )
                .exclude(cost_set__job_id__in=leave_job_ids())
                .values("cost_set__job__id", "cost_set__job__name")
                .annotate(total_hrs=Sum("quantity"))
                .order_by("-total_hrs")
                .first()
            )
            if top_job is None:
                self.stderr.write(
                    self.style.WARNING(
                        f"  {staff.get_display_name()}: no non-leave special job found, skipping"
                    )
                )
                continue
            result[staff] = _PrimaryJob(
                job_name=top_job["cost_set__job__name"],
                job_id=top_job["cost_set__job__id"],
                total_hours=float(top_job["total_hrs"]),
            )
        return result
