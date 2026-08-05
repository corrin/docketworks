"""Sales forecast: monthly Xero-invoice totals vs JM cost-line revenue.

Two accepted choices are recorded in rewrite status as cross-report
divergences: invoices count at ``total_incl_tax`` with DRAFT excluded (the
WIP report uses ``total_excl_tax`` and counts DRAFT), and the variance sign is
``xero - jm`` (payroll reconciliation reports ``jm - xero``).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import TypedDict

from django.db.models import Q, Sum

from apps.accounting.models import Invoice
from apps.job.models import Job
from apps.job.models.costing import CostLine

# Months before the company started using the app are hidden: their JM side
# is necessarily empty, so every row would be a meaningless "Xero only".
APP_ADOPTION_MONTH = "2025-04"

_EXCLUDED_INVOICE_STATUSES = ["DRAFT", "DELETED", "VOIDED"]


class ForecastMonth(TypedDict):
    """One month's Xero-vs-JM comparison."""

    month: str
    month_label: str
    xero_sales: float
    jm_sales: float
    variance: float
    variance_pct: float


class ForecastMonths(TypedDict):
    """The list-endpoint body."""

    months: list[ForecastMonth]


class ComparisonRow(TypedDict):
    """One matched / xero-only / jm-only row in the month drill-down."""

    date: str | None
    company_name: str
    job_number: int | None
    job_name: str | None
    invoice_numbers: str | None
    total_invoiced: float
    job_revenue: float
    variance: float
    job_id: str | None
    job_start_date: str | None
    total_xero_all_time: float | None
    total_jm_all_time: float | None
    variance_all_time: float | None
    note: str | None


class MonthDetail(TypedDict):
    """The detail-endpoint body."""

    month: str
    month_label: str
    rows: list[ComparisonRow]


def get_monthly_comparison() -> ForecastMonths:
    """All months with data from either source, newest first."""
    xero_by_month = _xero_sales_by_month()
    jm_by_month = _jm_sales_by_month()

    months = sorted(
        (m for m in set(xero_by_month) | set(jm_by_month) if m >= APP_ADOPTION_MONTH),
        reverse=True,
    )

    result: list[ForecastMonth] = []
    for month_key in months:
        xero_sales = float(xero_by_month.get(month_key, Decimal("0")))
        jm_sales = float(jm_by_month.get(month_key, Decimal("0")))
        variance = xero_sales - jm_sales
        year, month = month_key.split("-")
        result.append(
            ForecastMonth(
                month=month_key,
                month_label=date(int(year), int(month), 1).strftime("%b %Y"),
                xero_sales=xero_sales,
                jm_sales=jm_sales,
                variance=variance,
                variance_pct=round(variance / xero_sales * 100 if xero_sales != 0 else 0.0, 2),
            )
        )
    return ForecastMonths(months=result)


def get_month_detail(year: int, month: int) -> MonthDetail:
    """Build matched / xero-only / jm-only rows for one month, oldest first."""
    month_key = f"{year:04d}-{month:02d}"
    return MonthDetail(
        month=month_key,
        month_label=date(year, month, 1).strftime("%b %Y"),
        rows=_build_comparison_rows(year, month),
    )


def _xero_sales_by_month() -> dict[str, Decimal]:
    invoices = (
        Invoice.objects.filter(
            ~Q(status__in=_EXCLUDED_INVOICE_STATUSES),
            date__isnull=False,
        )
        .values("date")
        .annotate(total=Sum("total_incl_tax"))
    )
    sales: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for invoice in invoices:
        sales[invoice["date"].strftime("%Y-%m")] += invoice["total"] or Decimal("0")
    return dict(sales)


def _jm_sales_by_month() -> dict[str, Decimal]:
    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        accounting_date__isnull=False,
    )
    sales: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for line in lines:
        sales[line.accounting_date.strftime("%Y-%m")] += line.total_rev
    return dict(sales)


def _jobs_with_revenue(year: int, month: int) -> dict[str, Decimal]:
    """Jobs with non-zero actual revenue in the month."""
    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        accounting_date__year=year,
        accounting_date__month=month,
    ).select_related("cost_set__job")
    revenue: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for line in lines:
        revenue[str(line.cost_set.job.id)] += line.total_rev
    return {job_id: total for job_id, total in revenue.items() if total != 0}


def _total_invoiced_for_job(job: Job) -> float:
    total = Invoice.objects.filter(
        ~Q(status__in=_EXCLUDED_INVOICE_STATUSES),
        job=job,
    ).aggregate(total=Sum("total_incl_tax"))["total"]
    return float(total or 0)


def _job_note(job: Job | None, match_type: str) -> str | None:
    """Job characteristics first, then match status."""
    if job and job.shop_job:
        return "Shop job"
    if job:
        start = job.start_date
        end = job.last_financial_activity_date
        if start and end and (start.year, start.month) != (end.year, end.month):
            return "Multi-month"
    if match_type == "xero_only":
        return "Xero only"
    if match_type == "jm_only":
        return "JM only"
    return None


def _row(  # noqa: PLR0913 -- One keyword per response field.
    *,
    row_date: str | None,
    company_name: str,
    job_number: int | None,
    job_name: str | None,
    invoice_numbers: str | None,
    total_invoiced: float,
    job_revenue: float,
    job_id: str | None,
    job_start_date: str | None = None,
    total_xero_all_time: float | None = None,
    total_jm_all_time: float | None = None,
    note: str | None = None,
) -> ComparisonRow:
    variance_all_time = None
    if total_xero_all_time is not None and total_jm_all_time is not None:
        variance_all_time = round(total_xero_all_time - total_jm_all_time, 2)
    return ComparisonRow(
        date=row_date,
        company_name=company_name,
        job_number=job_number,
        job_name=job_name,
        invoice_numbers=invoice_numbers,
        total_invoiced=round(total_invoiced, 2),
        job_revenue=round(job_revenue, 2),
        variance=round(total_invoiced - job_revenue, 2),
        job_id=job_id,
        job_start_date=job_start_date,
        total_xero_all_time=total_xero_all_time,
        total_jm_all_time=total_jm_all_time,
        variance_all_time=variance_all_time,
        note=note,
    )


def _build_comparison_rows(year: int, month: int) -> list[ComparisonRow]:
    """One row per invoiced job, unlinked invoice, or uninvoiced revenue job."""
    rows: list[ComparisonRow] = []

    invoices = Invoice.objects.filter(
        ~Q(status__in=_EXCLUDED_INVOICE_STATUSES),
        date__year=year,
        date__month=month,
    ).select_related("company", "job", "job__company")
    revenue_by_job = _jobs_with_revenue(year, month)

    invoices_by_job: dict[str, list[Invoice]] = defaultdict(list)
    unlinked_invoices: list[Invoice] = []
    for invoice in invoices:
        if invoice.job:
            invoices_by_job[str(invoice.job.id)].append(invoice)
        else:
            unlinked_invoices.append(invoice)

    for job_id, job_invoices in invoices_by_job.items():
        job = job_invoices[0].job
        if job is None:  # partitioned on invoice.job above
            continue
        start = job.start_date
        rows.append(
            _row(
                row_date=job_invoices[0].date.isoformat(),
                company_name=job.company.name if job.company else "",
                job_number=job.job_number,
                job_name=job.name,
                invoice_numbers=", ".join(inv.number for inv in job_invoices),
                total_invoiced=sum(float(inv.total_incl_tax) for inv in job_invoices),
                job_revenue=float(revenue_by_job.get(job_id, Decimal("0"))),
                job_id=str(job.id),
                job_start_date=start.isoformat() if start else None,
                total_xero_all_time=_total_invoiced_for_job(job),
                total_jm_all_time=float(job.latest_actual.total_revenue)
                if job.latest_actual
                else 0.0,
                note=_job_note(job, "matched"),
            )
        )

    for invoice in unlinked_invoices:
        rows.append(
            _row(
                row_date=invoice.date.isoformat(),
                company_name=invoice.company.name,
                job_number=None,
                job_name=None,
                invoice_numbers=invoice.number,
                total_invoiced=float(invoice.total_incl_tax),
                job_revenue=0.0,
                job_id=None,
                note=_job_note(None, "xero_only"),
            )
        )

    for job_id, monthly_revenue in revenue_by_job.items():
        if job_id in invoices_by_job:
            continue
        job = Job.objects.select_related("company").get(id=job_id)
        start = job.start_date
        completion = job.last_financial_activity_date
        rows.append(
            _row(
                row_date=completion.isoformat() if completion else None,
                company_name=job.company.name if job.company else "",
                job_number=job.job_number,
                job_name=job.name,
                invoice_numbers=None,
                total_invoiced=0.0,
                job_revenue=float(monthly_revenue),
                job_id=str(job.id),
                job_start_date=start.isoformat() if start else None,
                total_xero_all_time=_total_invoiced_for_job(job),
                total_jm_all_time=float(job.latest_actual.total_revenue)
                if job.latest_actual
                else 0.0,
                note=_job_note(job, "jm_only"),
            )
        )

    rows.sort(key=lambda r: r["date"] or "")
    return rows
