"""Work-in-progress report: uninvoiced value of work performed, as at a date.

Ported from v1 ``apps/accounting/services/wip_service.py``. WIP is the value
of work on jobs not yet fully invoiced; partially-invoiced jobs subtract the
invoiced amount so the result is the *uninvoiced* remainder. Two valuation
methods: ``revenue`` (quantity x unit_rev) and ``cost`` (quantity x unit_cost).
"""

from datetime import date
from decimal import Decimal
from typing import TypedDict

from django.db.models import F, Q, Sum

from apps.accounting.models import Invoice
from apps.core.errors import AppErrorContext, persist_app_error
from apps.job.models import Job
from apps.job.models.costing import CostLine

# Statuses excluded from WIP entirely — no real work should exist yet.
NO_WORK_STATUSES = ["draft", "awaiting_approval"]

# Archived jobs are excluded from WIP but reported separately.
ARCHIVED_STATUS = "archived"

# Invoice statuses that count as "real" invoices. DRAFT is included here (a
# draft invoice already claims its WIP); the sales-forecast report makes the
# opposite call and excludes DRAFT — a deliberate v1 divergence between the
# two reports, kept as-is (rewrite-status records it).
VALID_INVOICE_STATUSES = ["DRAFT", "SUBMITTED", "AUTHORISED", "PAID"]


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
    base_qs = (
        Job.objects.filter(fully_invoiced=False, rejected_flag=False)
        .exclude(status__in=NO_WORK_STATUSES)
        .exclude(latest_actual__isnull=True)
        .select_related("latest_actual", "company")
        .order_by("job_number")
    )

    wip_jobs: list[WIPJobRow] = []
    archived_jobs: list[WIPJobRow] = []
    for job in base_qs:
        try:
            row = _aggregate_job(job, report_date, method)
        except Exception as exc:
            # One corrupt job must not take down the whole report.
            persist_app_error(
                exc,
                AppErrorContext(
                    job_id=job.id,
                    additional_context={
                        "operation": "wip_aggregate_job",
                        "job_number": job.job_number,
                        "report_date": str(report_date),
                        "method": method,
                    },
                ),
            )
            continue
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


def _aggregate_job(job: Job, report_date: date, method: str) -> WIPJobRow | None:
    """One job's WIP row, or None if it has zero revenue activity."""
    totals = CostLine.objects.filter(
        cost_set=job.latest_actual,
        accounting_date__lte=report_date,
    ).aggregate(
        total_cost=Sum(F("quantity") * F("unit_cost")),
        total_rev=Sum(F("quantity") * F("unit_rev")),
        time_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="time")),
        time_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="time")),
        material_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="material")),
        material_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="material")),
        adjust_cost=Sum(F("quantity") * F("unit_cost"), filter=Q(kind="adjust")),
        adjust_rev=Sum(F("quantity") * F("unit_rev"), filter=Q(kind="adjust")),
    )

    total_cost = totals["total_cost"] or Decimal("0")
    total_rev = totals["total_rev"] or Decimal("0")
    if total_rev == 0:
        return None

    invoiced = Invoice.objects.filter(
        job=job,
        status__in=VALID_INVOICE_STATUSES,
    ).aggregate(total=Sum("total_excl_tax"))["total"] or Decimal("0")

    gross_wip = total_rev if method == "revenue" else total_cost
    return WIPJobRow(
        job_number=job.job_number,
        name=job.name,
        company=str(job.company) if job.company else "N/A",
        status=job.status,
        time_cost=float(totals["time_cost"] or Decimal("0")),
        time_rev=float(totals["time_rev"] or Decimal("0")),
        material_cost=float(totals["material_cost"] or Decimal("0")),
        material_rev=float(totals["material_rev"] or Decimal("0")),
        adjust_cost=float(totals["adjust_cost"] or Decimal("0")),
        adjust_rev=float(totals["adjust_rev"] or Decimal("0")),
        total_cost=float(total_cost),
        total_rev=float(total_rev),
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
