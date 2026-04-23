"""Sales Pipeline Report service.

Implements every metric described in
``docs/plans/2026-04-16-sales-pipeline-report.md``. All metric calculation
lives here; views and serializers stay thin.

Reads transitions directly from structured ``JobEvent`` rows:
``event_type`` plus ``delta_after.status`` / ``delta_before.status``. No
description text parsing — PRs #218 / #220 and migrations 0075 / 0077 have
already populated structured fields for live and historical events.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import holidays
from django.db.models import QuerySet

from apps.job.models import Job
from apps.job.models.job_event import JobEvent
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)

# NZ-local timezone — the business operates here, and all date params are
# interpreted as NZ-local boundaries.
NZ_TZ = ZoneInfo("Pacific/Auckland")

# Job status keys (must stay in sync with apps/job/models/job.py
# Job.JOB_STATUS_CHOICES — raw keys, not display labels).
PIPELINE_STATUSES: frozenset[str] = frozenset({"draft", "awaiting_approval"})
APPROVED_STATUSES: frozenset[str] = frozenset({"approved", "in_progress"})

# Event types this service consumes.
EVT_STATUS_CHANGED = "status_changed"
EVT_QUOTE_ACCEPTED = "quote_accepted"
EVT_JOB_REJECTED = "job_rejected"
EVT_JOB_CREATED = "job_created"

RELEVANT_EVENT_TYPES: tuple[str, ...] = (
    EVT_STATUS_CHANGED,
    EVT_QUOTE_ACCEPTED,
    EVT_JOB_REJECTED,
    EVT_JOB_CREATED,
)

# Cap on how many sample job records each warning bucket carries back to the
# client. The full count is always reported.
WARNING_SAMPLE_CAP = 10

# Warning codes (machine-readable).
WARN_MISSING_HOURS = "missing_hours_summary"
WARN_MISSING_CREATION_ANCHOR = "missing_creation_anchor"


class SalesPipelineService:
    """Builds the Sales Pipeline Report."""

    # ─── Public entry point ────────────────────────────────────────────
    @classmethod
    def get_report(
        cls,
        start_date: date,
        end_date: date,
        rolling_window_weeks: int,
        trend_weeks: int,
    ) -> dict[str, Any]:
        warnings_state: dict[tuple[str, str], dict[str, Any]] = {}
        target = cls._load_company_target()

        events_by_job = cls._fetch_events(end_date)
        jobs_by_id = cls._fetch_jobs(events_by_job.keys())

        scoreboard = cls._build_scoreboard(
            events_by_job, jobs_by_id, start_date, end_date, target, warnings_state
        )
        snapshot = cls._build_snapshot(
            events_by_job, jobs_by_id, end_date, warnings_state
        )
        velocity = cls._build_velocity(
            events_by_job, jobs_by_id, start_date, end_date, warnings_state
        )
        funnel = cls._build_funnel(
            events_by_job, jobs_by_id, start_date, end_date, warnings_state
        )
        trend = cls._build_trend(
            events_by_job,
            jobs_by_id,
            end_date,
            trend_weeks,
            rolling_window_weeks,
        )

        return {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
                "rolling_window_weeks": rolling_window_weeks,
                "trend_weeks": trend_weeks,
                "daily_approved_hours_target": float(target),
            },
            "scoreboard": scoreboard,
            "pipeline_snapshot": snapshot,
            "velocity": velocity,
            "conversion_funnel": funnel,
            "trend": trend,
            "warnings": cls._format_warnings(warnings_state),
        }

    # ─── Loaders ───────────────────────────────────────────────────────
    @staticmethod
    def _load_company_target() -> Decimal:
        return CompanyDefaults.get_solo().daily_approved_hours_target

    @staticmethod
    def _fetch_events(end_date: date) -> dict[Any, list[JobEvent]]:
        end_dt = datetime.combine(end_date, time.max, tzinfo=NZ_TZ)
        events: QuerySet[JobEvent] = JobEvent.objects.filter(
            event_type__in=RELEVANT_EVENT_TYPES,
            timestamp__lte=end_dt,
            job__isnull=False,
        ).order_by("timestamp")
        grouped: dict[Any, list[JobEvent]] = defaultdict(list)
        for evt in events:
            grouped[evt.job_id].append(evt)
        return grouped

    @staticmethod
    def _fetch_jobs(job_ids: Iterable[Any]) -> dict[Any, Job]:
        ids = list(job_ids)
        if not ids:
            return {}
        jobs = Job.objects.filter(id__in=ids).select_related(
            "latest_quote", "latest_estimate", "client"
        )
        return {j.id: j for j in jobs}

    # ─── Date / timezone helpers ───────────────────────────────────────
    @staticmethod
    def _to_local_date(dt: datetime) -> date:
        return dt.astimezone(NZ_TZ).date()

    @staticmethod
    def _local_day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
        start_dt = datetime.combine(start, time.min, tzinfo=NZ_TZ)
        end_dt = datetime.combine(end, time.max, tzinfo=NZ_TZ)
        return start_dt, end_dt

    @staticmethod
    def _end_of_local_day(d: date) -> datetime:
        return datetime.combine(d, time.max, tzinfo=NZ_TZ)

    @staticmethod
    def _week_start(d: date) -> date:
        # ISO week — Monday is day 0.
        return d - timedelta(days=d.weekday())

    @staticmethod
    def _working_days_between(start: date, end: date) -> int:
        if end < start:
            return 0
        years = set(range(start.year, end.year + 1))
        nz_holidays = holidays.country_holidays("NZ", years=years)
        count = 0
        d = start
        while d <= end:
            if d.weekday() < 5 and d not in nz_holidays:
                count += 1
            d += timedelta(days=1)
        return count

    # ─── Replay / qualifying-event helpers ─────────────────────────────
    @classmethod
    def _replay_status_as_of(
        cls, events: list[JobEvent], cutoff_dt: datetime
    ) -> str | None:
        """Walk events in timestamp order, resolving the job status as of
        ``cutoff_dt``. Returns ``None`` when there is no creation anchor with
        a usable ``delta_after.status``.
        """
        anchor_seen = False
        status: str | None = None
        for evt in events:
            if evt.timestamp > cutoff_dt:
                break
            delta_after = evt.delta_after or {}
            if evt.event_type == EVT_JOB_CREATED:
                if "status" in delta_after:
                    status = delta_after["status"]
                    anchor_seen = True
            elif evt.event_type in (
                EVT_STATUS_CHANGED,
                EVT_QUOTE_ACCEPTED,
                EVT_JOB_REJECTED,
            ):
                if "status" in delta_after:
                    status = delta_after["status"]
        return status if anchor_seen else None

    @classmethod
    def _qualifying_approval_event(
        cls,
        events: list[JobEvent],
        period_start_dt: datetime,
        period_end_dt: datetime,
    ) -> JobEvent | None:
        """Earliest event in ``[period_start_dt, period_end_dt]`` that
        qualifies as an approval transition: ``status_changed`` whose
        ``delta_after.status`` is approved/in_progress, OR ``quote_accepted``.
        """
        for evt in events:
            if evt.timestamp < period_start_dt:
                continue
            if evt.timestamp > period_end_dt:
                break
            if evt.event_type == EVT_QUOTE_ACCEPTED:
                return evt
            if evt.event_type == EVT_STATUS_CHANGED:
                delta = evt.delta_after or {}
                if delta.get("status") in APPROVED_STATUSES:
                    return evt
        return None

    @staticmethod
    def _earliest_status_change_to(
        events: list[JobEvent], target_status: str
    ) -> JobEvent | None:
        for evt in events:
            if evt.event_type != EVT_STATUS_CHANGED:
                continue
            delta = evt.delta_after or {}
            if delta.get("status") == target_status:
                return evt
        return None

    @staticmethod
    def _earliest_event_of_type(
        events: list[JobEvent], event_type: str
    ) -> JobEvent | None:
        for evt in events:
            if evt.event_type == event_type:
                return evt
        return None

    @staticmethod
    def _had_event_before(
        events: list[JobEvent],
        event_type: str,
        cutoff_dt: datetime,
        status_filter: set[str] | frozenset[str] | None = None,
    ) -> bool:
        for evt in events:
            if evt.timestamp >= cutoff_dt:
                break
            if evt.event_type != event_type:
                continue
            if status_filter is None:
                return True
            delta = evt.delta_after or {}
            if delta.get("status") in status_filter:
                return True
        return False

    @staticmethod
    def _last_status_change_into(
        events: list[JobEvent], target_status: str, cutoff_dt: datetime
    ) -> JobEvent | None:
        last: JobEvent | None = None
        for evt in events:
            if evt.timestamp > cutoff_dt:
                break
            if evt.event_type != EVT_STATUS_CHANGED:
                continue
            delta = evt.delta_after or {}
            if delta.get("status") == target_status:
                last = evt
        return last

    # ─── Hours / value resolution ──────────────────────────────────────
    @staticmethod
    def _summary_hours(summary: dict | None) -> float | None:
        if not summary:
            return None
        h = summary.get("hours")
        return None if h is None else float(h)

    @staticmethod
    def _summary_value(summary: dict | None) -> float | None:
        if not summary:
            return None
        v = summary.get("rev")
        return None if v is None else float(v)

    @classmethod
    def _resolve_hours_quote_first(cls, job: Job) -> float | None:
        if job.latest_quote_id and job.latest_quote:
            h = cls._summary_hours(job.latest_quote.summary)
            if h is not None:
                return h
        if job.latest_estimate_id and job.latest_estimate:
            return cls._summary_hours(job.latest_estimate.summary)
        return None

    @classmethod
    def _resolve_quote_hours(cls, job: Job) -> float | None:
        if job.latest_quote_id and job.latest_quote:
            return cls._summary_hours(job.latest_quote.summary)
        return None

    @classmethod
    def _resolve_estimate_hours(cls, job: Job) -> float | None:
        if job.latest_estimate_id and job.latest_estimate:
            return cls._summary_hours(job.latest_estimate.summary)
        return None

    @classmethod
    def _resolve_quote_value(cls, job: Job) -> float | None:
        if job.latest_quote_id and job.latest_quote:
            return cls._summary_value(job.latest_quote.summary)
        return None

    @classmethod
    def _resolve_estimate_value(cls, job: Job) -> float | None:
        if job.latest_estimate_id and job.latest_estimate:
            return cls._summary_value(job.latest_estimate.summary)
        return None

    # ─── Warning bookkeeping ───────────────────────────────────────────
    @staticmethod
    def _add_warning(
        state: dict[tuple[str, str], dict[str, Any]],
        code: str,
        section: str,
        job: Job | None,
    ) -> None:
        key = (code, section)
        bucket = state.setdefault(
            key,
            {"code": code, "section": section, "count": 0, "sample_jobs": []},
        )
        bucket["count"] += 1
        if job is not None and len(bucket["sample_jobs"]) < WARNING_SAMPLE_CAP:
            bucket["sample_jobs"].append(
                {
                    "id": str(job.id),
                    "job_number": getattr(job, "job_number", None),
                    "name": getattr(job, "name", ""),
                }
            )

    @staticmethod
    def _format_warnings(
        state: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return list(state.values())

    @staticmethod
    def _stats(values: list[float]) -> dict[str, Any]:
        n = len(values)
        if n == 0:
            return {"median_days": None, "p80_days": None, "sample_size": 0}
        ordered = sorted(values)
        p80_idx = max(0, min(n - 1, int(round(0.8 * (n - 1)))))
        return {
            "median_days": float(median(ordered)),
            "p80_days": float(ordered[p80_idx]),
            "sample_size": n,
        }

    # ─── Section: Scoreboard ───────────────────────────────────────────
    @classmethod
    def _build_scoreboard(
        cls,
        events_by_job: dict[Any, list[JobEvent]],
        jobs_by_id: dict[Any, Job],
        start_date: date,
        end_date: date,
        target: Decimal,
        warnings: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        period_start, period_end = cls._local_day_bounds(start_date, end_date)

        approved_hours_total = 0.0
        approved_jobs_count = 0
        direct_hours = 0.0
        direct_jobs_count = 0

        for job_id, events in events_by_job.items():
            qe = cls._qualifying_approval_event(events, period_start, period_end)
            if qe is None:
                continue
            job = jobs_by_id.get(job_id)
            if job is None:
                continue
            hours = cls._resolve_hours_quote_first(job)
            if hours is None:
                cls._add_warning(warnings, WARN_MISSING_HOURS, "scoreboard", job)
                continue
            approved_hours_total += hours
            approved_jobs_count += 1

            had_prior_awaiting = cls._had_event_before(
                events,
                EVT_STATUS_CHANGED,
                qe.timestamp,
                status_filter={"awaiting_approval"},
            )
            had_prior_quote_accepted = cls._had_event_before(
                events, EVT_QUOTE_ACCEPTED, qe.timestamp
            )
            if not had_prior_awaiting and not had_prior_quote_accepted:
                direct_hours += hours
                direct_jobs_count += 1

        working_days = cls._working_days_between(start_date, end_date)
        target_hours = float(target) * working_days
        pace = (approved_hours_total / target_hours) if target_hours > 0 else None

        return {
            "approved_hours_total": approved_hours_total,
            "approved_jobs_count": approved_jobs_count,
            "direct_hours": direct_hours,
            "direct_jobs_count": direct_jobs_count,
            "working_days": working_days,
            "target_hours_for_period": target_hours,
            "pace_vs_target": pace,
        }

    # ─── Section: Pipeline Snapshot ────────────────────────────────────
    @classmethod
    def _build_snapshot(
        cls,
        events_by_job: dict[Any, list[JobEvent]],
        jobs_by_id: dict[Any, Job],
        end_date: date,
        warnings: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        cutoff = cls._end_of_local_day(end_date)

        stages: dict[str, dict[str, Any]] = {
            "draft": {
                "count": 0,
                "hours_total": 0.0,
                "value_total": 0.0,
                "_days_sum": 0,
                "_days_n": 0,
                "jobs": [],
            },
            "awaiting_approval": {
                "count": 0,
                "hours_total": 0.0,
                "value_total": 0.0,
                "_days_sum": 0,
                "_days_n": 0,
                "jobs": [],
            },
        }

        for job_id, events in events_by_job.items():
            creation = cls._earliest_event_of_type(events, EVT_JOB_CREATED)
            anchor_status = (
                (creation.delta_after or {}).get("status") if creation else None
            )
            if creation is None or anchor_status is None:
                cls._add_warning(
                    warnings,
                    WARN_MISSING_CREATION_ANCHOR,
                    "pipeline_snapshot",
                    jobs_by_id.get(job_id),
                )
                continue

            replayed = cls._replay_status_as_of(events, cutoff)
            if replayed not in PIPELINE_STATUSES:
                continue
            job = jobs_by_id.get(job_id)
            if job is None:
                continue

            if replayed == "draft":
                hours = cls._resolve_estimate_hours(job)
                value = cls._resolve_estimate_value(job)
            else:
                hours = cls._resolve_quote_hours(job)
                value = cls._resolve_quote_value(job)

            if hours is None:
                cls._add_warning(warnings, WARN_MISSING_HOURS, "pipeline_snapshot", job)
                continue

            last_into = cls._last_status_change_into(events, replayed, cutoff)
            entered_dt = last_into.timestamp if last_into else creation.timestamp
            days_in_stage = max(0, (end_date - cls._to_local_date(entered_dt)).days)

            bucket = stages[replayed]
            bucket["count"] += 1
            bucket["hours_total"] += hours
            bucket["value_total"] += value or 0.0
            bucket["_days_sum"] += days_in_stage
            bucket["_days_n"] += 1
            bucket["jobs"].append(
                {
                    "id": str(job.id),
                    "job_number": job.job_number,
                    "name": job.name,
                    "client_name": job.client.name if job.client_id else "",
                    "hours": hours,
                    "value": value or 0.0,
                    "days_in_stage": days_in_stage,
                }
            )

        def _avg_days(b: dict[str, Any]) -> float:
            return (b["_days_sum"] / b["_days_n"]) if b["_days_n"] else 0.0

        return {
            "as_of": end_date,
            "draft": {
                "count": stages["draft"]["count"],
                "hours_total": stages["draft"]["hours_total"],
                "value_total": stages["draft"]["value_total"],
                "avg_days_in_stage": _avg_days(stages["draft"]),
                "jobs": stages["draft"]["jobs"],
            },
            "awaiting_approval": {
                "count": stages["awaiting_approval"]["count"],
                "hours_total": stages["awaiting_approval"]["hours_total"],
                "value_total": stages["awaiting_approval"]["value_total"],
                "avg_days_in_stage": _avg_days(stages["awaiting_approval"]),
                "jobs": stages["awaiting_approval"]["jobs"],
            },
        }

    # ─── Section: Velocity ─────────────────────────────────────────────
    @classmethod
    def _build_velocity(
        cls,
        events_by_job: dict[Any, list[JobEvent]],
        jobs_by_id: dict[Any, Job],
        start_date: date,
        end_date: date,
        warnings: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        period_start, period_end = cls._local_day_bounds(start_date, end_date)

        draft_to_quote: list[float] = []
        quote_to_resolved: list[float] = []
        created_to_approved: list[float] = []

        for job_id, events in events_by_job.items():
            creation = cls._earliest_event_of_type(events, EVT_JOB_CREATED)
            first_to_awaiting = cls._earliest_status_change_to(
                events, "awaiting_approval"
            )
            first_approved = cls._earliest_status_change_to(events, "approved")
            first_quote_accepted = cls._earliest_event_of_type(
                events, EVT_QUOTE_ACCEPTED
            )
            first_rejected = cls._earliest_event_of_type(events, EVT_JOB_REJECTED)

            # Per the plan: a job with no job_created anchor or no usable
            # delta_after.status is excluded from velocity with a warning —
            # only warn for jobs that would otherwise have contributed
            # (i.e. have at least one velocity-relevant event in-period).
            relevant_in_period = any(
                e and period_start <= e.timestamp <= period_end
                for e in (
                    first_to_awaiting,
                    first_approved,
                    first_quote_accepted,
                    first_rejected,
                )
            )
            anchor_status = (
                (creation.delta_after or {}).get("status") if creation else None
            )
            if relevant_in_period and (creation is None or anchor_status is None):
                cls._add_warning(
                    warnings,
                    WARN_MISSING_CREATION_ANCHOR,
                    "velocity",
                    jobs_by_id.get(job_id),
                )
                continue

            if (
                creation
                and first_to_awaiting
                and period_start <= first_to_awaiting.timestamp <= period_end
            ):
                days = (
                    cls._to_local_date(first_to_awaiting.timestamp)
                    - cls._to_local_date(creation.timestamp)
                ).days
                draft_to_quote.append(max(days, 0))

            if first_to_awaiting:
                resolution_candidates = [
                    e
                    for e in (first_approved, first_quote_accepted, first_rejected)
                    if e and e.timestamp > first_to_awaiting.timestamp
                ]
                if resolution_candidates:
                    resolution = min(resolution_candidates, key=lambda e: e.timestamp)
                    if period_start <= resolution.timestamp <= period_end:
                        days = (
                            cls._to_local_date(resolution.timestamp)
                            - cls._to_local_date(first_to_awaiting.timestamp)
                        ).days
                        quote_to_resolved.append(max(days, 0))

            approval_candidates = [
                e for e in (first_approved, first_quote_accepted) if e
            ]
            if creation and approval_candidates:
                approval = min(approval_candidates, key=lambda e: e.timestamp)
                if period_start <= approval.timestamp <= period_end:
                    days = (
                        cls._to_local_date(approval.timestamp)
                        - cls._to_local_date(creation.timestamp)
                    ).days
                    created_to_approved.append(max(days, 0))

        return {
            "draft_to_quote_sent": cls._stats(draft_to_quote),
            "quote_sent_to_resolved": cls._stats(quote_to_resolved),
            "created_to_approved": cls._stats(created_to_approved),
        }

    # ─── Section: Conversion Funnel ────────────────────────────────────
    @classmethod
    def _build_funnel(
        cls,
        events_by_job: dict[Any, list[JobEvent]],
        jobs_by_id: dict[Any, Job],
        start_date: date,
        end_date: date,
        warnings: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        period_start, period_end = cls._local_day_bounds(start_date, end_date)
        cutoff = period_end

        buckets: dict[str, dict[str, float]] = {
            "accepted": {"count": 0, "hours": 0.0},
            "rejected": {"count": 0, "hours": 0.0},
            "waiting": {"count": 0, "hours": 0.0},
            "direct": {"count": 0, "hours": 0.0},
            "still_draft": {"count": 0, "hours": 0.0},
        }

        for job_id, events in events_by_job.items():
            creation = cls._earliest_event_of_type(events, EVT_JOB_CREATED)
            anchor_status = (
                (creation.delta_after or {}).get("status") if creation else None
            )
            if creation is None or anchor_status is None:
                # Per the plan: jobs with no job_created anchor are excluded
                # with a warning rather than silently dropped. Only warn for
                # jobs whose (fallback) creation timestamp falls in-period so
                # we don't flood warnings for pre-existing jobs that weren't
                # created during the reporting window.
                fallback_ts = events[0].timestamp if events else None
                if fallback_ts and period_start <= fallback_ts <= period_end:
                    cls._add_warning(
                        warnings,
                        WARN_MISSING_CREATION_ANCHOR,
                        "conversion_funnel",
                        jobs_by_id.get(job_id),
                    )
                continue
            if not (period_start <= creation.timestamp <= period_end):
                continue
            job = jobs_by_id.get(job_id)
            if job is None:
                continue

            replayed = cls._replay_status_as_of(events, cutoff)

            had_awaiting = any(
                e.event_type == EVT_STATUS_CHANGED
                and (e.delta_after or {}).get("status") == "awaiting_approval"
                and e.timestamp <= cutoff
                for e in events
            )
            had_quote_accepted = any(
                e.event_type == EVT_QUOTE_ACCEPTED and e.timestamp <= cutoff
                for e in events
            )
            had_rejected = any(
                e.event_type == EVT_JOB_REJECTED and e.timestamp <= cutoff
                for e in events
            )
            had_approval = had_quote_accepted or any(
                e.event_type == EVT_STATUS_CHANGED
                and (e.delta_after or {}).get("status") in APPROVED_STATUSES
                and e.timestamp <= cutoff
                for e in events
            )

            quote_stage_reached = had_awaiting or had_quote_accepted
            hours = (
                cls._resolve_quote_hours(job)
                if quote_stage_reached
                else cls._resolve_estimate_hours(job)
            )
            if hours is None:
                cls._add_warning(warnings, WARN_MISSING_HOURS, "conversion_funnel", job)
                continue

            if had_rejected:
                bucket_key = "rejected"
            elif had_approval:
                bucket_key = "accepted" if quote_stage_reached else "direct"
            elif replayed == "awaiting_approval":
                bucket_key = "waiting"
            elif replayed == "draft":
                bucket_key = "still_draft"
            else:
                continue

            buckets[bucket_key]["count"] += 1
            buckets[bucket_key]["hours"] += hours

        return buckets

    # ─── Section: Trend ────────────────────────────────────────────────
    @classmethod
    def _build_trend(
        cls,
        events_by_job: dict[Any, list[JobEvent]],
        jobs_by_id: dict[Any, Job],
        end_date: date,
        trend_weeks: int,
        rolling_window_weeks: int,
    ) -> dict[str, Any]:
        end_week_start = cls._week_start(end_date)
        weeks: list[dict[str, Any]] = []

        for i in range(trend_weeks):
            week_start = end_week_start - timedelta(weeks=trend_weeks - 1 - i)
            natural_week_end = week_start + timedelta(days=6)
            week_end = min(natural_week_end, end_date)
            week = cls._build_trend_week(
                events_by_job, jobs_by_id, week_start, week_end
            )
            weeks.append(week)

        approved_series = [w["approved_hours"] for w in weeks]
        rolling: list[dict[str, Any]] = []
        for i in range(len(weeks)):
            window = approved_series[max(0, i - rolling_window_weeks + 1) : i + 1]
            avg = sum(window) / len(window) if window else 0.0
            rolling.append(
                {
                    "week_start": weeks[i]["week_start"],
                    "rolling_avg_approved_hours": avg,
                }
            )

        return {"weeks": weeks, "rolling_average": rolling}

    @classmethod
    def _build_trend_week(
        cls,
        events_by_job: dict[Any, list[JobEvent]],
        jobs_by_id: dict[Any, Job],
        week_start: date,
        week_end: date,
    ) -> dict[str, Any]:
        period_start, period_end = cls._local_day_bounds(week_start, week_end)
        cutoff = period_end

        approved_hours = 0.0
        accepted_hours = 0.0
        rejected_hours = 0.0
        velocity_samples: list[float] = []
        pipeline_hours = 0.0

        for job_id, events in events_by_job.items():
            job = jobs_by_id.get(job_id)
            qe = cls._qualifying_approval_event(events, period_start, period_end)
            if qe and job:
                h = cls._resolve_hours_quote_first(job)
                if h is not None:
                    approved_hours += h
                    accepted_hours += h

            for evt in events:
                if (
                    evt.event_type == EVT_JOB_REJECTED
                    and period_start <= evt.timestamp <= period_end
                ):
                    if job:
                        h = cls._resolve_hours_quote_first(job)
                        if h is not None:
                            rejected_hours += h
                    break

            creation = cls._earliest_event_of_type(events, EVT_JOB_CREATED)
            first_approved = cls._earliest_status_change_to(events, "approved")
            first_quote_accepted = cls._earliest_event_of_type(
                events, EVT_QUOTE_ACCEPTED
            )
            approval_candidates = [
                e for e in (first_approved, first_quote_accepted) if e
            ]
            if creation and approval_candidates:
                approval = min(approval_candidates, key=lambda e: e.timestamp)
                if period_start <= approval.timestamp <= period_end:
                    days = (
                        cls._to_local_date(approval.timestamp)
                        - cls._to_local_date(creation.timestamp)
                    ).days
                    velocity_samples.append(max(days, 0))

            if creation and (creation.delta_after or {}).get("status"):
                replayed = cls._replay_status_as_of(events, cutoff)
                if replayed in PIPELINE_STATUSES and job:
                    h = (
                        cls._resolve_estimate_hours(job)
                        if replayed == "draft"
                        else cls._resolve_quote_hours(job)
                    )
                    if h is not None:
                        pipeline_hours += h

        working_days = cls._working_days_between(week_start, week_end)
        per_wd = approved_hours / working_days if working_days > 0 else 0.0
        accept_denom = accepted_hours + rejected_hours
        accept_rate = accepted_hours / accept_denom if accept_denom > 0 else None
        median_velocity = float(median(velocity_samples)) if velocity_samples else None

        return {
            "week_start": week_start,
            "week_end": week_end,
            "approved_hours": approved_hours,
            "approved_hours_per_working_day": per_wd,
            "acceptance_rate_by_hours": accept_rate,
            "pipeline_hours_at_week_end": pipeline_hours,
            "median_velocity_days": median_velocity,
            "working_days": working_days,
        }
