"""Job aging report: per-job financial totals, timing, and last activity.

Ported from v1 ``apps/accounting/services/core.py`` (JobAgingService) minus
v1's guard thicket: every v1 try/except here either protected a sum over
prefetched rows that cannot fail on its own, or served the report *around*
malformed data (a corrupt staff reference degraded the row to null activity
fields and, via a swallowed sort TypeError, silently unsorted the whole
report). v2 stops instead: malformed data persists an AppError with the job
named and fails the request — fix the data, never read around it (ADR 0015;
the 2026-08 production restore has zero such rows). Ledgered.
"""

import datetime
from typing import TypedDict

from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet


class FinancialTotals(TypedDict):
    """Revenue totals from the three latest cost sets."""

    estimate_total: float
    quote_total: float
    actual_total: float


class TimingData(TypedDict):
    """Creation, status-dwell, and last-activity timing for one job."""

    created_date: str
    created_days_ago: int
    days_in_current_status: int
    last_activity_date: str | None
    last_activity_days_ago: int | None
    last_activity_type: str | None
    last_activity_description: str | None


class JobAgingRow(TypedDict):
    """One job in the aging report."""

    id: str
    job_number: int
    name: str
    company_name: str
    status: str
    status_display: str
    financial_data: FinancialTotals
    timing_data: TimingData


class JobAgingData(TypedDict):
    """The whole report body."""

    jobs: list[JobAgingRow]


class _Activity(TypedDict):
    """One candidate "last activity" with its timestamp."""

    date: datetime.datetime
    type: str
    description: str


class _LastActivity(TypedDict):
    """The winning activity, flattened for the response."""

    last_activity_date: str
    last_activity_days_ago: int
    last_activity_type: str
    last_activity_description: str


def get_job_aging_data(*, include_archived: bool = False) -> JobAgingData:
    """All jobs (most recent activity first, archived filtered) with aging data."""
    jobs_query = Job.objects.select_related("company").prefetch_related(
        "events", "cost_sets__cost_lines"
    )
    if not include_archived:
        jobs_query = jobs_query.exclude(status="archived")

    job_data = [
        JobAgingRow(
            id=str(job.id),
            job_number=job.job_number,
            name=job.name,
            company_name=job.company.name if job.company else "No Company",
            status=job.status,
            status_display=job.get_status_display(),
            financial_data=_financial_totals(job),
            timing_data=_timing_data(job),
        )
        for job in jobs_query.order_by("-created_at")
    ]

    # Most recent activity first (v1's sort key). last_activity_days_ago is
    # never None in practice — every job carries updated_at — but the wire
    # contract keeps the field nullable, so the key stays total.
    job_data.sort(
        key=lambda row: (
            row["timing_data"]["last_activity_days_ago"] is None,
            row["timing_data"]["last_activity_days_ago"] or 0,
        )
    )
    return JobAgingData(jobs=job_data)


def _financial_totals(job: Job) -> FinancialTotals:
    """Estimate/quote/actual revenue totals from the three latest cost sets."""

    def total(cost_set: CostSet | None) -> float:
        if cost_set is None:
            return 0.0
        return float(sum(line.total_rev for line in cost_set.cost_lines.all()))

    return FinancialTotals(
        estimate_total=total(job.latest_estimate),
        quote_total=total(job.latest_quote),
        actual_total=total(job.latest_actual),
    )


def _timing_data(job: Job) -> TimingData:
    today = timezone.localdate()
    created_date = timezone.localtime(job.created_at).date()
    last = _last_activity(job)
    return TimingData(
        created_date=created_date.isoformat(),
        created_days_ago=(today - created_date).days,
        days_in_current_status=_days_in_current_status(job),
        last_activity_date=last["last_activity_date"] if last else None,
        last_activity_days_ago=last["last_activity_days_ago"] if last else None,
        last_activity_type=last["last_activity_type"] if last else None,
        last_activity_description=last["last_activity_description"] if last else None,
    )


def _days_in_current_status(job: Job) -> int:
    # v1 filtered on "status_change", which nothing writes (the tracker emits
    # "status_changed"), so this always fell through to the creation date.
    # Fixed here; ledgered as a v1 defect.
    latest_status_change = job.events.filter(event_type="status_changed").first()
    if latest_status_change is None:
        return (timezone.localdate() - timezone.localtime(job.created_at).date()).days
    return (timezone.now() - latest_status_change.timestamp).days


def _last_activity(job: Job) -> _LastActivity | None:
    """Most recent activity across job events, the job row, and cost lines."""
    activities: list[_Activity] = []

    latest_event = job.events.first()  # Meta.ordering is -timestamp
    if latest_event is not None:
        activities.append(
            _Activity(
                date=latest_event.timestamp,
                type="job_event",
                description=f"{latest_event.event_type}: {latest_event.description}",
            )
        )

    if job.updated_at:
        activities.append(
            _Activity(
                date=job.updated_at,
                type="job_update",
                description="Job record updated",
            )
        )

    for cost_set in job.cost_sets.all():
        for cost_line in cost_set.cost_lines.all():
            description = f"{cost_line.get_kind_display()} entry: {cost_line.desc}"
            # Only actual time entries have staff; estimate/quote lines are
            # planning entries.
            if cost_line.kind == "time" and cost_set.kind == "actual":
                staff = _resolve_staff(job, cost_line)
                description = f"Time added by {staff.get_display_full_name()}"
            activities.append(
                _Activity(
                    date=datetime.datetime.combine(
                        cost_line.accounting_date,
                        datetime.time.min,
                        tzinfo=timezone.get_current_timezone(),
                    ),
                    type=f"cost_line_{cost_line.kind}",
                    description=description,
                )
            )

    if not activities:
        return None

    latest = max(activities, key=lambda activity: activity["date"])
    activity_date = timezone.localtime(latest["date"]).date()
    return _LastActivity(
        last_activity_date=activity_date.isoformat(),
        last_activity_days_ago=(timezone.localdate() - activity_date).days,
        last_activity_type=latest["type"],
        last_activity_description=latest["description"],
    )


def _resolve_staff(job: Job, cost_line: CostLine) -> Staff:
    """Return the line's staff member; a dangling reference is corrupt data (ADR 0015)."""
    staff = cost_line.staff
    if staff is None:
        exc = ValueError(
            "Corrupted cost line staff reference detected "
            f"(job_id={job.id}, cost_line_id={cost_line.id}, "
            f"staff_id={cost_line.staff_id})"
        )
        persist_app_error(
            exc,
            AppErrorContext(
                job_id=job.id,
                additional_context={
                    "operation": "cost_line_staff_resolution",
                    "cost_line_id": str(cost_line.id),
                    "staff_id": str(cost_line.staff_id),
                },
            ),
        )
        raise exc
    return staff
