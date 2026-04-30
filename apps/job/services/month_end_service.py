import logging
from decimal import Decimal
from typing import List, Tuple

from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.job.models import CostSet, Job
from apps.purchasing.models import Stock

logger = logging.getLogger(__name__)


class MonthEndService:
    @staticmethod
    def _get_stock_job() -> Job:
        return Stock.get_stock_holding_job()

    @staticmethod
    def get_special_jobs() -> List[Job]:
        stock_job = MonthEndService._get_stock_job()
        return list(Job.objects.filter(status="special").exclude(id=stock_job.id))

    @staticmethod
    def _build_job_history(job: Job) -> List[dict]:
        history = []
        for cs in (
            job.cost_sets.filter(kind="actual")
            .exclude(id=job.latest_actual_id)
            .order_by("created")
        ):
            history.append(
                {
                    "date": cs.created,
                    "total_hours": Decimal(str(cs.summary.get("hours", 0))),
                    "total_dollars": Decimal(str(cs.summary.get("cost", 0))),
                }
            )
        return history

    @staticmethod
    def get_special_jobs_data() -> List[dict]:
        data = []
        for job in MonthEndService.get_special_jobs():
            actual = job.latest_actual
            data.append(
                {
                    "job": job,
                    "history": MonthEndService._build_job_history(job),
                    "total_hours": (
                        Decimal(str(actual.summary.get("hours", 0)))
                        if actual
                        else Decimal("0")
                    ),
                    "total_dollars": (
                        Decimal(str(actual.summary.get("cost", 0)))
                        if actual
                        else Decimal("0")
                    ),
                }
            )
        return data

    @staticmethod
    def get_stock_job_data() -> dict:
        job = MonthEndService._get_stock_job()
        history = []
        for cs in job.cost_sets.filter(kind="actual").order_by("created"):
            material_lines = cs.cost_lines.filter(kind="material")
            total_cost = sum(
                (line.total_cost for line in material_lines),
                Decimal("0"),
            )
            history.append(
                {
                    "date": cs.created,
                    "material_line_count": material_lines.count(),
                    "material_cost": total_cost,
                }
            )
        return {"job": job, "history": history}

    @staticmethod
    def process_jobs(
        job_ids: List[str], staff
    ) -> Tuple[List[Job], List[Tuple[str, str]]]:
        processed_jobs: List[Job] = []
        error_jobs: List[Tuple[str, str]] = []
        for job_id in job_ids:
            try:
                job = get_object_or_404(Job, id=job_id)
                with transaction.atomic():
                    rev = job.cost_sets.filter(kind="actual").count() + 1
                    new_set = CostSet.objects.create(
                        job=job,
                        kind="actual",
                        rev=rev,
                        summary={"cost": 0, "rev": 0, "hours": 0},
                    )
                    job.set_latest("actual", new_set, staff)
                processed_jobs.append(job)
            except Exception as e:
                logger.exception("Error processing job %s", job_id)
                error_jobs.append((job_id, str(e)))
        return processed_jobs, error_jobs
