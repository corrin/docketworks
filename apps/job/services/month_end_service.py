"""Month-end data and cost-set rollover for special jobs (v1 ``month_end_service.py``).

The month-end screen reviews jobs with status ``special`` (shop/overhead
jobs, excluding the stock-holding job) plus the stock job's material history,
then rolls each selected job forward by opening a NEW empty ``actual`` cost
set — nothing is archived; the previous cost sets simply become the history.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db import transaction

from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models import CostSet, Job
from apps.purchasing.models import Stock

logger = logging.getLogger(__name__)


class SpecialJobHistoryEntry(TypedDict):
    """One prior (non-latest) actual cost set of a special job."""

    date: datetime
    total_hours: Decimal
    total_dollars: Decimal


class SpecialJobData(TypedDict):
    """A special job with its latest-actual totals and prior cost sets."""

    job: Job
    history: list[SpecialJobHistoryEntry]
    total_hours: Decimal
    total_dollars: Decimal


class StockHistoryEntry(TypedDict):
    """Material totals for one actual cost set of the stock-holding job."""

    date: datetime
    material_line_count: int
    material_cost: Decimal


class StockJobData(TypedDict):
    """The stock-holding job with per-cost-set material totals."""

    job: Job
    history: list[StockHistoryEntry]


def get_special_jobs() -> list[Job]:
    """Special-status jobs eligible for month-end, excluding the stock job."""
    stock_job = Stock.get_stock_holding_job()
    return list(Job.objects.filter(status="special").exclude(id=stock_job.id))


def _build_job_history(job: Job) -> list[SpecialJobHistoryEntry]:
    # summary.get(..., 0): summaries are free JSON and v1-era rows may lack
    # keys, so this read stays tolerant rather than KeyError-ing (v1 parity).
    return [
        SpecialJobHistoryEntry(
            date=cost_set.created,
            total_hours=Decimal(str(cost_set.summary.get("hours", 0))),
            total_dollars=Decimal(str(cost_set.summary.get("cost", 0))),
        )
        for cost_set in job.cost_sets.filter(kind="actual")
        .exclude(id=job.latest_actual_id)
        .order_by("created")
    ]


def get_special_jobs_data() -> list[SpecialJobData]:
    """Per special job: latest-actual totals plus the prior actual cost sets."""
    data: list[SpecialJobData] = []
    for job in get_special_jobs():
        actual = job.latest_actual
        data.append(
            SpecialJobData(
                job=job,
                history=_build_job_history(job),
                total_hours=(
                    Decimal(str(actual.summary.get("hours", 0))) if actual else Decimal("0")
                ),
                total_dollars=(
                    Decimal(str(actual.summary.get("cost", 0))) if actual else Decimal("0")
                ),
            )
        )
    return data


def get_stock_job_data() -> StockJobData:
    """Return the stock-holding job with material totals for EVERY actual cost set.

    Unlike the special-job history, the latest cost set is included — the
    stock screen shows the running period too.
    """
    job = Stock.get_stock_holding_job()
    history: list[StockHistoryEntry] = []
    for cost_set in job.cost_sets.filter(kind="actual").order_by("created"):
        material_lines = list(cost_set.cost_lines.filter(kind="material"))
        history.append(
            StockHistoryEntry(
                date=cost_set.created,
                material_line_count=len(material_lines),
                material_cost=sum((line.total_cost for line in material_lines), Decimal("0")),
            )
        )
    return StockJobData(job=job, history=history)


def process_jobs(job_ids: list[UUID], staff: Staff) -> tuple[list[Job], list[str]]:
    """Roll each job forward: a new empty ``actual`` cost set becomes latest.

    A failing id must not abort the rest of the batch, so each failure is
    persisted (AppError) and reported as ``"<job_id>: <error>"``. v1 collected
    ``(id, message)`` tuples here, but its response serializer declared plain
    strings — the tuple shape could never leave the endpoint (it 400-ed on
    response validation), so v2 serves the declared string contract.
    """
    processed_jobs: list[Job] = []
    errors: list[str] = []
    for job_id in job_ids:
        try:
            job = Job.objects.get(id=job_id)
            with transaction.atomic():
                rev = job.cost_sets.filter(kind="actual").count() + 1
                new_set = CostSet.objects.create(
                    job=job,
                    kind="actual",
                    rev=rev,
                    summary={"cost": 0, "rev": 0, "hours": 0},
                )
                job.set_latest("actual", new_set, staff)
        except Exception as exc:
            logger.exception("Error processing job %s", job_id)
            persist_app_error(
                exc,
                AppErrorContext(job_id=str(job_id), user_id=str(staff.id)),
            )
            errors.append(f"{job_id}: {exc}")
            continue
        processed_jobs.append(job)
    return processed_jobs, errors
