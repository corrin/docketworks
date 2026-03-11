import logging
from collections import defaultdict
from datetime import date
from typing import Any

from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce

from apps.job.enums import RDTIType
from apps.job.models.costing import CostLine
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)

# All RDTI categories we always include, with labels
_RDTI_CATEGORIES: list[tuple[str, str]] = [
    (choice.value, choice.label) for choice in RDTIType
] + [("unclassified", "Unclassified")]


def _persist_and_raise(exception: Exception, **context: Any) -> None:
    """Persist an exception and re-raise as AlreadyLoggedException."""
    app_error = persist_app_error(exception, **context)
    raise AlreadyLoggedException(exception, app_error.id)


class RDTISpendService:
    @staticmethod
    def get_rdti_spend_data(start_date: date, end_date: date) -> dict[str, Any]:
        try:
            return RDTISpendService._build_report(start_date, end_date)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            _persist_and_raise(
                exc,
                additional_context={
                    "operation": "rdti_spend_report",
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                },
            )
            raise  # unreachable but keeps type checker happy

    @staticmethod
    def _build_report(start_date: date, end_date: date) -> dict[str, Any]:
        job_rows = (
            CostLine.objects.filter(
                cost_set__kind="actual",
                accounting_date__gte=start_date,
                accounting_date__lte=end_date,
            )
            .values(
                job_id=F("cost_set__job__id"),
                job_number=F("cost_set__job__job_number"),
                job_name=F("cost_set__job__name"),
                client_name=F("cost_set__job__client__name"),
                rdti_type=Coalesce(
                    F("cost_set__job__rdti_type"), Value("unclassified")
                ),
            )
            .annotate(
                hours=Coalesce(Sum("quantity"), 0.0),
                cost=Coalesce(Sum(F("quantity") * F("unit_cost")), 0.0),
                revenue=Coalesce(Sum(F("quantity") * F("unit_rev")), 0.0),
            )
            .order_by("-cost")
        )

        # Build per-job detail list
        jobs: list[dict[str, Any]] = []
        for row in job_rows:
            jobs.append(
                {
                    "job_id": str(row["job_id"]),
                    "job_number": row["job_number"],
                    "job_name": row["job_name"],
                    "client_name": row["client_name"] or "",
                    "rdti_type": row["rdti_type"],
                    "hours": float(row["hours"]),
                    "cost": float(row["cost"]),
                    "revenue": float(row["revenue"]),
                }
            )

        # Aggregate into category summaries
        cat_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"hours": 0.0, "cost": 0.0, "revenue": 0.0, "job_count": 0}
        )
        for job in jobs:
            cat = cat_data[job["rdti_type"]]
            cat["hours"] += job["hours"]
            cat["cost"] += job["cost"]
            cat["revenue"] += job["revenue"]
            cat["job_count"] += 1

        # Build summary with all 4 categories (even if zero)
        summary = []
        for rdti_value, label in _RDTI_CATEGORIES:
            data = cat_data.get(rdti_value, {})
            summary.append(
                {
                    "rdti_type": rdti_value,
                    "label": label,
                    "hours": data.get("hours", 0.0),
                    "cost": data.get("cost", 0.0),
                    "revenue": data.get("revenue", 0.0),
                    "job_count": data.get("job_count", 0),
                }
            )

        totals = {
            "hours": sum(s["hours"] for s in summary),
            "cost": sum(s["cost"] for s in summary),
            "revenue": sum(s["revenue"] for s in summary),
        }

        return {
            "start_date": start_date,
            "end_date": end_date,
            "summary": summary,
            "jobs": jobs,
            "totals": totals,
        }
