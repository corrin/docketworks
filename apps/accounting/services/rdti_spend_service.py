"""RDTI spend report: actual cost lines grouped by job and R&D classification.

Ported from v1 ``apps/accounting/services/rdti_spend_service.py`` — one SQL
aggregate, no Python loops over cost lines. Jobs with a NULL ``rdti_type``
report as "unclassified", and the summary always lists all four categories.
"""

from collections import defaultdict
from datetime import date
from typing import TypedDict

from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce

from apps.job.enums import RDTIType
from apps.job.models.costing import CostLine

# All RDTI categories, always included in the summary (even at zero).
_RDTI_CATEGORIES: list[tuple[str, str]] = [(choice.value, choice.label) for choice in RDTIType] + [
    ("unclassified", "Unclassified")
]


class RDTIJobDetail(TypedDict):
    """Per-job spend within the period."""

    job_id: str
    job_number: int
    job_name: str
    company_name: str
    rdti_type: str
    hours: float
    cost: float
    revenue: float


class RDTICategorySummary(TypedDict):
    """One RDTI category's aggregate."""

    rdti_type: str
    label: str
    hours: float
    cost: float
    revenue: float
    job_count: int


class RDTITotals(TypedDict):
    """Grand totals across every category."""

    hours: float
    cost: float
    revenue: float


class RDTISpendData(TypedDict):
    """The whole report body."""

    start_date: date
    end_date: date
    summary: list[RDTICategorySummary]
    jobs: list[RDTIJobDetail]
    totals: RDTITotals


def get_rdti_spend_data(start_date: date, end_date: date) -> RDTISpendData:
    """Spend per job and per RDTI category over the inclusive date range."""
    money = DecimalField(max_digits=13, decimal_places=2)
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
            company_name=F("cost_set__job__company__name"),
            rdti_type=Coalesce(F("cost_set__job__rdti_type"), Value("unclassified")),
        )
        .annotate(
            hours=Coalesce(Sum("quantity"), Value(0), output_field=money),
            cost=Coalesce(Sum(F("quantity") * F("unit_cost")), Value(0), output_field=money),
            revenue=Coalesce(Sum(F("quantity") * F("unit_rev")), Value(0), output_field=money),
        )
        .order_by("-cost")
    )

    jobs = [
        RDTIJobDetail(
            job_id=str(row["job_id"]),
            job_number=row["job_number"],
            job_name=row["job_name"],
            company_name=row["company_name"] or "",
            rdti_type=row["rdti_type"],
            hours=float(row["hours"]),
            cost=float(row["cost"]),
            revenue=float(row["revenue"]),
        )
        for row in job_rows
    ]

    cat_data: dict[str, dict[str, float]] = defaultdict(
        lambda: {"hours": 0.0, "cost": 0.0, "revenue": 0.0, "job_count": 0}
    )
    for job in jobs:
        cat = cat_data[job["rdti_type"]]
        cat["hours"] += job["hours"]
        cat["cost"] += job["cost"]
        cat["revenue"] += job["revenue"]
        cat["job_count"] += 1

    summary = [
        RDTICategorySummary(
            rdti_type=rdti_value,
            label=label,
            hours=cat_data[rdti_value]["hours"] if rdti_value in cat_data else 0.0,
            cost=cat_data[rdti_value]["cost"] if rdti_value in cat_data else 0.0,
            revenue=cat_data[rdti_value]["revenue"] if rdti_value in cat_data else 0.0,
            job_count=int(cat_data[rdti_value]["job_count"]) if rdti_value in cat_data else 0,
        )
        for rdti_value, label in _RDTI_CATEGORIES
    ]

    return RDTISpendData(
        start_date=start_date,
        end_date=end_date,
        summary=summary,
        jobs=jobs,
        totals=RDTITotals(
            hours=sum(s["hours"] for s in summary),
            cost=sum(s["cost"] for s in summary),
            revenue=sum(s["revenue"] for s in summary),
        ),
    )
