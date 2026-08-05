"""Work-in-progress report: uninvoiced value of work performed, as at a date.

WIP is the value of work on jobs not yet fully invoiced; partially-invoiced
jobs subtract the
invoiced amount so the result is the *uninvoiced* remainder. Two valuation
methods: ``revenue`` (quantity x unit_rev) and ``cost`` (quantity x unit_cost).
"""

from datetime import date
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db.models import F, Q, Sum

from apps.accounting.models import Invoice
from apps.job.models import Job
from apps.job.models.costing import CostLine

# Statuses excluded from WIP entirely — no real work should exist yet.
NO_WORK_STATUSES = ["draft", "awaiting_approval"]

# Archived jobs are excluded from WIP but reported separately.
ARCHIVED_STATUS = "archived"

# Invoice statuses that count as "real" invoices. DRAFT is included here (a
# draft invoice already claims its WIP); the sales-forecast report makes the
# opposite call and excludes DRAFT — a deliberate divergence between the
# two reports, kept as-is (rewrite-status records it).
VALID_INVOICE_STATUSES = ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID"]


class _CostTotals(TypedDict):
    """One cost set's cost/revenue splits, zero-filled at the query boundary."""

    total_cost: Decimal
    total_rev: Decimal
    time_cost: Decimal
    time_rev: Decimal
    material_cost: Decimal
    material_rev: Decimal
    adjust_cost: Decimal
    adjust_rev: Decimal


def _zero_totals() -> _CostTotals:
    return _CostTotals(
        total_cost=Decimal("0"),
        total_rev=Decimal("0"),
        time_cost=Decimal("0"),
        time_rev=Decimal("0"),
        material_cost=Decimal("0"),
        material_rev=Decimal("0"),
        adjust_cost=Decimal("0"),
        adjust_rev=Decimal("0"),
    )


class WIPJobRow(TypedDict):
    """One job's WIP row."""

    job_number: int
    name: str
    company: str
    status: str
    time_cost: float
    time_rev: float
    material_cost: float
    material_rev: float
    adjust_cost: float
    adjust_rev: float
    total_cost: float
    total_rev: float
    invoiced: float
    gross_wip: float
    net_wip: float


class WIPStatusBreakdown(TypedDict):
    """WIP subtotal for one job status."""

    status: str
    count: int
    net_wip: float


class WIPSummary(TypedDict):
    """Report-level totals."""

    job_count: int
    total_gross: float
    total_invoiced: float
    total_net: float
    by_status: list[WIPStatusBreakdown]


class WIPData(TypedDict):
    """The whole report body."""

    jobs: list[WIPJobRow]
    archived_jobs: list[WIPJobRow]
    summary: WIPSummary
    report_date: str
    method: str


def get_wip_data(report_date: date, method: str) -> WIPData:
    """WIP rows (net descending), archived rows, and summary as at the date."""
    jobs = list(
        Job.objects.filter(fully_invoiced=False, rejected_flag=False)
        .exclude(status__in=NO_WORK_STATUSES)
        .exclude(latest_actual__isnull=True)
        .select_related("latest_actual", "company")
        .order_by("job_number")
    )

    # Two grouped queries, not two per job: the production restore has ~540
    # eligible jobs, so the per-job form cost 1 + 2N ≈ 1,100 queries.
    cost_totals = _cost_totals_by_cost_set([job.latest_actual_id for job in jobs], report_date)
    invoiced_totals = _invoiced_totals_by_job([job.id for job in jobs])

    wip_jobs: list[WIPJobRow] = []
    archived_jobs: list[WIPJobRow] = []
    for job in jobs:
        row = _build_row(
            job,
            cost_totals.get(job.latest_actual_id, _zero_totals()),
            invoiced_totals.get(job.id, Decimal("0")),
            method,
        )
        if row is None:
            continue
        if job.status == ARCHIVED_STATUS:
            archived_jobs.append(row)
        else:
            wip_jobs.append(row)

    wip_jobs.sort(key=lambda r: r["net_wip"], reverse=True)
    archived_jobs.sort(key=lambda r: r["net_wip"], reverse=True)

    return WIPData(
        jobs=wip_jobs,
        archived_jobs=archived_jobs,
        summary=_build_summary(wip_jobs),
        report_date=str(report_date),
        method=method,
    )


def _cost_totals_by_cost_set(
    cost_set_ids: list[UUID], report_date: date
) -> dict[UUID, _CostTotals]:
    """Per-cost-set cost/revenue splits for lines dated on or before the date.

    Aliased ``agg_*`` because ``total_cost``/``total_rev`` are CostLine
    properties and Django refuses an annotation that shadows a model attribute.
    """
    rows = (
        CostLine.objects.filter(
            cost_set_id__in=cost_set_ids,
            accounting_date__lte=report_date,
        )
        .values("cost_set_id")
        .annotate(
            agg_total_cost=Sum(F("quantity") * F("unit_cost")),
            agg_total_rev=Sum(F("quantity") * F("unit_rev")),
            agg_time_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="time")),
            agg_time_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="time")),
            agg_material_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="material")),
            agg_material_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="material")),
            agg_adjust_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="adjust")),
            agg_adjust_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="adjust")),
        )
    )
    return {
        row["cost_set_id"]: _CostTotals(
            total_cost=row["agg_total_cost"] or Decimal("0"),
            total_rev=row["agg_total_rev"] or Decimal("0"),
            time_cost=row["agg_time_cost"] or Decimal("0"),
            time_rev=row["agg_time_rev"] or Decimal("0"),
            material_cost=row["agg_material_cost"] or Decimal("0"),
            material_rev=row["agg_material_rev"] or Decimal("0"),
            adjust_cost=row["agg_adjust_cost"] or Decimal("0"),
            adjust_rev=row["agg_adjust_rev"] or Decimal("0"),
        )
        for row in rows
    }


def _invoiced_totals_by_job(job_ids: list[UUID]) -> dict[UUID, Decimal]:
    """Per-job invoiced totals over the statuses that count as real invoices."""
    rows = (
        Invoice.objects.filter(job_id__in=job_ids, status__in=VALID_INVOICE_STATUSES)
        .values("job_id")
        .annotate(total=Sum("total_excl_tax"))
    )
    return {row["job_id"]: row["total"] or Decimal("0") for row in rows}


def _build_row(job: Job, totals: _CostTotals, invoiced: Decimal, method: str) -> WIPJobRow | None:
    """One job's WIP row, or None if it has zero revenue activity."""
    if totals["total_rev"] == 0:
        return None

    gross_wip = totals["total_rev"] if method == "revenue" else totals["total_cost"]
    return WIPJobRow(
        job_number=job.job_number,
        name=job.name,
        company=str(job.company) if job.company else "N/A",
        status=job.status,
        time_cost=float(totals["time_cost"]),
        time_rev=float(totals["time_rev"]),
        material_cost=float(totals["material_cost"]),
        material_rev=float(totals["material_rev"]),
        adjust_cost=float(totals["adjust_cost"]),
        adjust_rev=float(totals["adjust_rev"]),
        total_cost=float(totals["total_cost"]),
        total_rev=float(totals["total_rev"]),
        invoiced=float(invoiced),
        gross_wip=float(gross_wip),
        net_wip=float(gross_wip - invoiced),
    )


def _build_summary(wip_jobs: list[WIPJobRow]) -> WIPSummary:
    by_status: dict[str, WIPStatusBreakdown] = {}
    total_gross = total_invoiced = total_net = 0.0
    for row in wip_jobs:
        total_gross += row["gross_wip"]
        total_invoiced += row["invoiced"]
        total_net += row["net_wip"]
        bucket = by_status.setdefault(
            row["status"],
            WIPStatusBreakdown(status=row["status"], count=0, net_wip=0.0),
        )
        bucket["count"] += 1
        bucket["net_wip"] += row["net_wip"]

    return WIPSummary(
        job_count=len(wip_jobs),
        total_gross=total_gross,
        total_invoiced=total_invoiced,
        total_net=total_net,
        by_status=sorted(by_status.values(), key=lambda b: b["net_wip"], reverse=True),
    )
