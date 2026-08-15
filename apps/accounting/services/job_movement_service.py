"""Job movement metrics: job lifecycle and quote-conversion counts.

Report semantics:

- The period is INCLUSIVE of both dates, via ``report_windows`` — the same
  window every other report uses.
- "Quotes submitted/accepted" count EVENTS, so a job bouncing in and out of
  awaiting_approval counts twice; the sales-pipeline report counts each job
  once — a cross-report divergence recorded in rewrite-status.
- "Won" and "rejected" read the job's CURRENT status/flag, not its state
  within the period.
"""

from datetime import date, datetime, timedelta
from typing import TypedDict

from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting.services.report_windows import local_day_bounds
from apps.job.models import Job
from apps.job.models.job_event import JobEvent


class ComparisonDelta(TypedDict):
    """Change vs the comparison period (merged into a metric when requested)."""

    comparison_value: float
    change: float
    change_percent: float


def _draft_jobs_created(start: datetime, end: datetime) -> QuerySet[Job]:
    return Job.objects.filter(created_at__gte=start, created_at__lte=end).select_related(
        "company", "created_by"
    )


def _quotes_submitted(start: datetime, end: datetime) -> QuerySet[JobEvent]:
    return JobEvent.objects.filter(
        event_type="status_changed",
        timestamp__gte=start,
        timestamp__lte=end,
        delta_after__status="awaiting_approval",
    ).select_related("job", "staff")


def _quotes_accepted(start: datetime, end: datetime) -> QuerySet[JobEvent]:
    return JobEvent.objects.filter(
        event_type="status_changed",
        timestamp__gte=start,
        timestamp__lte=end,
        delta_after__status="approved",
    ).select_related("job", "staff")


class _JobsWonData(TypedDict):
    """Won/draft/rejected partition of the period's created jobs."""

    total_created: int
    still_draft: QuerySet[Job]
    still_draft_count: int
    won_jobs: QuerySet[Job]
    won_count: int
    rejected_jobs: QuerySet[Job]
    rejected_count: int


def _jobs_won(start: datetime, end: datetime) -> _JobsWonData:
    all_jobs = _draft_jobs_created(start, end)
    still_draft = all_jobs.filter(status="draft")
    won_jobs = all_jobs.exclude(status="draft").exclude(rejected_flag=True)
    rejected_jobs = all_jobs.filter(rejected_flag=True)
    return _JobsWonData(
        total_created=all_jobs.count(),
        still_draft=still_draft,
        still_draft_count=still_draft.count(),
        won_jobs=won_jobs,
        won_count=won_jobs.count(),
        rejected_jobs=rejected_jobs,
        rejected_count=rejected_jobs.count(),
    )


class _PathData(TypedDict):
    """Quoted-vs-direct partition of the period's progressed jobs."""

    through_quotes: QuerySet[Job]
    through_quotes_count: int
    skip_quotes: QuerySet[Job]
    skip_quotes_count: int


def _jobs_by_status_path(start: datetime, end: datetime) -> _PathData:
    all_jobs = Job.objects.filter(created_at__gte=start, created_at__lte=end)
    through_ids = set(_quotes_submitted(start, end).values_list("job_id", flat=True))
    skip_quotes = all_jobs.exclude(id__in=through_ids).exclude(status="draft")
    return _PathData(
        through_quotes=Job.objects.filter(id__in=through_ids),
        through_quotes_count=len(through_ids),
        skip_quotes=skip_quotes,
        skip_quotes_count=skip_quotes.count(),
    )


def _rate(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator * 100


def _comparison(current: float, comparison: float) -> ComparisonDelta:
    if comparison == 0:
        change_percent = 0.0 if current == 0 else (100.0 if current > 0 else -100.0)
    else:
        change_percent = (current - comparison) / comparison * 100
    return ComparisonDelta(
        comparison_value=comparison,
        change=current - comparison,
        change_percent=change_percent,
    )


class JobListItem(TypedDict):
    """One job in an include_details listing."""

    id: str
    job_number: int
    name: str
    company_name: str | None
    status: str
    status_display: str
    created_at: str


class EventListItem(TypedDict):
    """One quote event in an include_details listing."""

    id: str
    job_id: str
    job_number: int
    job_name: str
    company_name: str | None
    timestamp: str
    current_status: str
    current_status_display: str


def _serialize_jobs(jobs: QuerySet[Job]) -> list[JobListItem]:
    return [
        JobListItem(
            id=str(job.id),
            job_number=job.job_number,
            name=job.name,
            company_name=job.company.name if job.company else None,
            status=job.status,
            status_display=job.get_status_display(),
            created_at=job.created_at.isoformat(),
        )
        for job in jobs
    ]


def _serialize_events(events: QuerySet[JobEvent]) -> list[EventListItem]:
    return [
        EventListItem(
            id=str(event.id),
            job_id=str(event.job.id),
            job_number=event.job.job_number,
            job_name=event.job.name,
            company_name=event.job.company.name if event.job.company else None,
            timestamp=event.timestamp.isoformat(),
            current_status=event.job.status,
            current_status_display=event.job.get_status_display(),
        )
        for event in events
        if event.job  # events can outlive their job
    ]


class _PeriodCounts(TypedDict):
    """All raw counts for one period."""

    draft_count: int
    quotes_submitted_count: int
    quotes_accepted_count: int
    jobs_data: _JobsWonData
    path_data: _PathData


def _period_counts(start: datetime, end: datetime) -> _PeriodCounts:
    return _PeriodCounts(
        draft_count=_draft_jobs_created(start, end).count(),
        quotes_submitted_count=_quotes_submitted(start, end).count(),
        quotes_accepted_count=_quotes_accepted(start, end).count(),
        jobs_data=_jobs_won(start, end),
        path_data=_jobs_by_status_path(start, end),
    )


def _baseline_metrics(baseline_days: int) -> dict[str, object]:
    """Totals, weekly averages, and rates over a trailing window."""
    end = timezone.now()
    start = end - timedelta(days=baseline_days)
    counts = _period_counts(start, end)
    weeks = baseline_days / 7.0

    total_progressed = (
        counts["path_data"]["through_quotes_count"] + counts["path_data"]["skip_quotes_count"]
    )
    return {
        "period_days": baseline_days,
        "weeks": round(weeks, 2),
        "totals": {
            "draft_jobs_created": counts["draft_count"],
            "quotes_submitted": counts["quotes_submitted_count"],
            "quotes_accepted": counts["quotes_accepted_count"],
            "jobs_won": counts["jobs_data"]["won_count"],
            "rejected": counts["jobs_data"]["rejected_count"],
            "through_quotes": counts["path_data"]["through_quotes_count"],
            "skip_quotes": counts["path_data"]["skip_quotes_count"],
        },
        "weekly_averages": {
            "draft_jobs_created": round(counts["draft_count"] / weeks, 2),
            "quotes_submitted": round(counts["quotes_submitted_count"] / weeks, 2),
            "quotes_accepted": round(counts["quotes_accepted_count"] / weeks, 2),
            "jobs_won": round(counts["jobs_data"]["won_count"] / weeks, 2),
            "rejected": round(counts["jobs_data"]["rejected_count"] / weeks, 2),
        },
        "rates": {
            "quote_acceptance_rate": round(
                _rate(counts["quotes_accepted_count"], counts["quotes_submitted_count"]),
                1,
            ),
            "draft_conversion_rate": round(
                _rate(
                    counts["jobs_data"]["won_count"],
                    counts["jobs_data"]["total_created"],
                ),
                1,
            ),
            "quote_usage_rate": round(
                _rate(counts["path_data"]["through_quotes_count"], total_progressed), 1
            ),
        },
    }


def get_job_movement_metrics(  # noqa: PLR0913 -- Report filters stay explicit and keyword-only.
    start_date: date,
    end_date: date,
    *,
    compare_start_date: date | None = None,
    compare_end_date: date | None = None,
    baseline_days: int | None = None,
    include_details: bool = False,
) -> dict[str, object]:
    """Build the full job-movement report body."""
    start, end = local_day_bounds(start_date, end_date)

    draft_jobs = _draft_jobs_created(start, end)
    quotes_submitted_events = _quotes_submitted(start, end)
    quotes_accepted_events = _quotes_accepted(start, end)
    jobs_data = _jobs_won(start, end)
    path_data = _jobs_by_status_path(start, end)

    draft_count = draft_jobs.count()
    quotes_submitted_count = quotes_submitted_events.count()
    quotes_accepted_count = quotes_accepted_events.count()
    acceptance_rate = _rate(quotes_accepted_count, quotes_submitted_count)
    conversion_rate = _rate(jobs_data["won_count"], jobs_data["total_created"])
    total_progressed = path_data["through_quotes_count"] + path_data["skip_quotes_count"]
    quote_usage_percent = _rate(path_data["through_quotes_count"], total_progressed)

    comparison = None
    if compare_start_date is not None and compare_end_date is not None:
        comp_counts = _period_counts(*local_day_bounds(compare_start_date, compare_end_date))
        comparison = {
            "draft_jobs_created": comp_counts["draft_count"],
            "quotes_submitted": comp_counts["quotes_submitted_count"],
            "quotes_accepted": comp_counts["quotes_accepted_count"],
            "quote_acceptance_rate": _rate(
                comp_counts["quotes_accepted_count"],
                comp_counts["quotes_submitted_count"],
            ),
            "jobs_won": comp_counts["jobs_data"]["won_count"],
            "draft_conversion_rate": _rate(
                comp_counts["jobs_data"]["won_count"],
                comp_counts["jobs_data"]["total_created"],
            ),
            # through_quotes is the only path figure any response field
            # compares; v1 also computed skip_quotes and quote-usage here and
            # read neither.
            "through_quotes": comp_counts["path_data"]["through_quotes_count"],
        }

    def with_comparison(base: dict[str, object], key: str, current: float) -> dict[str, object]:
        if comparison is None:
            return base
        # No float() coercion: v1 emitted ints for count comparisons and
        # floats for rates, and mypy accepts int where float is declared.
        return {**base, **_comparison(current, comparison[key])}

    response: dict[str, object] = {
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": (end_date - start_date).days + 1,
        },
        "metrics": {
            "draft_jobs_created": with_comparison(
                {"count": draft_count}, "draft_jobs_created", draft_count
            ),
            "quotes_submitted": with_comparison(
                {"count": quotes_submitted_count},
                "quotes_submitted",
                quotes_submitted_count,
            ),
            "quotes_accepted": with_comparison(
                {"count": quotes_accepted_count},
                "quotes_accepted",
                quotes_accepted_count,
            ),
            "quote_acceptance_rate": with_comparison(
                {
                    "rate": acceptance_rate,
                    "numerator": quotes_accepted_count,
                    "denominator": quotes_submitted_count,
                },
                "quote_acceptance_rate",
                acceptance_rate,
            ),
            "jobs_won": with_comparison(
                {
                    "count": jobs_data["won_count"],
                    "still_draft": jobs_data["still_draft_count"],
                    "rejected": jobs_data["rejected_count"],
                    "total_created": jobs_data["total_created"],
                },
                "jobs_won",
                jobs_data["won_count"],
            ),
            "draft_conversion_rate": with_comparison(
                {
                    "rate": conversion_rate,
                    "numerator": jobs_data["won_count"],
                    "denominator": jobs_data["total_created"],
                },
                "draft_conversion_rate",
                conversion_rate,
            ),
            "workflow_paths": with_comparison(
                {
                    "through_quotes": path_data["through_quotes_count"],
                    "skip_quotes": path_data["skip_quotes_count"],
                    "still_draft": jobs_data["still_draft_count"],
                    "quote_usage_percent": quote_usage_percent,
                },
                "through_quotes",
                path_data["through_quotes_count"],
            ),
        },
    }

    if compare_start_date is not None and compare_end_date is not None:
        response["comparison_period"] = {
            "start_date": compare_start_date.isoformat(),
            "end_date": compare_end_date.isoformat(),
            "days": (compare_end_date - compare_start_date).days + 1,
        }

    if baseline_days:
        response["baseline"] = _baseline_metrics(baseline_days)

    if include_details:
        response["details"] = {
            "draft_jobs": _serialize_jobs(draft_jobs),
            "quotes_submitted": _serialize_events(quotes_submitted_events),
            "quotes_accepted": _serialize_events(quotes_accepted_events),
            "jobs_won": _serialize_jobs(jobs_data["won_jobs"]),
            "jobs_still_draft": _serialize_jobs(jobs_data["still_draft"]),
            "jobs_rejected": _serialize_jobs(jobs_data["rejected_jobs"]),
            "jobs_through_quotes": _serialize_jobs(path_data["through_quotes"]),
            "jobs_skip_quotes": _serialize_jobs(path_data["skip_quotes"]),
        }

    return response
