"""The accounting domain's ninja router (thin translators over apps.accounting.services).

Paths and operationIds match v1's generated OpenAPI schema (frontend/schema.yml):
thirteen read-only report endpoints under ``/api/accounting/reports/``. Three of
them lived in v1's ``apps/workflow/api/reports`` (job-movement, payroll
reconciliation, profit-and-loss); they move here because the concept is an
accounting report and this app is its one home (sanctioned by the plan:
"reports move from workflow/api/ to accounting/").

Auth: every endpoint is plain ``CookieJWTAuth`` — v1 set no permission class on
any report view, so DRF's default IsAuthenticated applied; there is no office
or superuser gate on this surface.

Error bodies use the v2 envelope ``{"detail", "error_id"}``, not v1's
``StandardErrorSerializer`` ``{"error", "details"}`` shape (ledgered:
accounting-reports-wide).

Integration wiring (config/api.py): ``api.add_router("/accounting/", router)``.
"""

import datetime
import uuid
from typing import Literal

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja.errors import ValidationError as RequestValidationError

from apps.accounting.schemas import (
    JobAgingResponse,
    KPICalendarResponse,
    RDTISpendResponse,
    SalesForecastMonthDetailResponse,
    SalesForecastResponse,
    StaffPerformanceResponse,
    WIPResponse,
)
from apps.accounting.services import (
    job_aging_service,
    job_movement_service,
    kpi_service,
    rdti_spend_service,
    sales_forecast_service,
    staff_performance_service,
    wip_service,
)
from apps.core.auth import CookieJWTAuth

router = Router(tags=["accounting"], auth=CookieJWTAuth())


def _require_ordered(start_date: datetime.date, end_date: datetime.date) -> None:
    """Reject an inverted date range before running any report."""
    if start_date > end_date:
        raise RequestValidationError(errors=[{"msg": "start_date must not be after end_date."}])


@router.get(
    "/reports/job-aging/",
    operation_id="accounting_reports_job_aging_retrieve",
    summary="Job aging report",
    response=JobAgingResponse,
)
def job_aging(
    request: HttpRequest, include_archived: bool = False
) -> job_aging_service.JobAgingData:
    """Every job with financial totals, timing data, and last activity."""
    return job_aging_service.get_job_aging_data(include_archived=include_archived)


@router.get(
    "/reports/wip/",
    operation_id="accounting_reports_wip_retrieve",
    summary="Work-in-progress report",
    response=WIPResponse,
)
def wip_report(
    request: HttpRequest,
    date: datetime.date | None = None,
    method: Literal["revenue", "cost"] = "revenue",
) -> wip_service.WIPData:
    """Uninvoiced WIP per job as at the given date (defaults to today)."""
    report_date = date if date is not None else timezone.localdate()
    return wip_service.get_wip_data(report_date, method)


@router.get(
    "/reports/rdti-spend/",
    operation_id="accounting_reports_rdti_spend_retrieve",
    summary="RDTI spend report",
    response=RDTISpendResponse,
)
def rdti_spend(
    request: HttpRequest, start_date: datetime.date, end_date: datetime.date
) -> rdti_spend_service.RDTISpendData:
    """Actual spend grouped by job and R&D classification for the period."""
    if start_date > end_date:
        raise RequestValidationError(errors=[{"msg": "start_date must not be after end_date."}])
    return rdti_spend_service.get_rdti_spend_data(start_date, end_date)


@router.get(
    "/reports/job-movement/",
    operation_id="accounting_reports_job_movement_retrieve",
    summary="Job movement and conversion metrics",
    response=dict,  # v1 declared an untyped OBJECT; the comparison/baseline/
    # details sections merge in dynamically, so dict keeps schema parity
)
def job_movement(  # noqa: PLR0913, PLR0917 -- one query param per v1 report filter
    request: HttpRequest,
    start_date: datetime.date,
    end_date: datetime.date,
    compare_start_date: datetime.date | None = None,
    compare_end_date: datetime.date | None = None,
    baseline_days: int | None = None,
    include_details: bool = False,
) -> dict[str, object]:
    """Job lifecycle and quote-conversion counts for management meetings."""
    if baseline_days is not None and baseline_days <= 0:
        raise RequestValidationError(errors=[{"msg": "baseline_days must be a positive integer"}])
    # v1 required BOTH compare dates; one without the other was silently
    # ignored, and that is kept.
    has_comparison = compare_start_date is not None and compare_end_date is not None
    return job_movement_service.get_job_movement_metrics(
        start_date,
        end_date,
        compare_start_date=compare_start_date if has_comparison else None,
        compare_end_date=compare_end_date if has_comparison else None,
        baseline_days=baseline_days,
        include_details=include_details,
    )


@router.get(
    "/reports/sales-forecast/",
    operation_id="sales_forecast_list",
    summary="Monthly sales forecast data",
    response=SalesForecastResponse,
)
def sales_forecast(request: HttpRequest) -> sales_forecast_service.ForecastMonths:
    """Compare monthly Xero invoice totals with JM revenue, newest first."""
    return sales_forecast_service.get_monthly_comparison()


@router.get(
    "/reports/sales-forecast/{month}/",
    operation_id="sales_forecast_month_detail",
    summary="Month detail for sales forecast",
    response=SalesForecastMonthDetailResponse,
)
def sales_forecast_month_detail(
    request: HttpRequest, month: str
) -> sales_forecast_service.MonthDetail:
    """Drill into one month: matched, Xero-only, and JM-only rows."""
    year_int, month_int = _parse_forecast_month(month)
    return sales_forecast_service.get_month_detail(year_int, month_int)


def _parse_forecast_month(month: str) -> tuple[int, int]:
    """Validate the YYYY-MM path segment, including the app-adoption floor."""
    if len(month) != 7 or month[4] != "-":
        raise RequestValidationError(errors=[{"msg": "Invalid month format. Use YYYY-MM"}])
    try:
        year_int, month_int = int(month[:4]), int(month[5:])
    except ValueError as exc:
        raise RequestValidationError(errors=[{"msg": f"Invalid month: {exc}"}]) from exc
    if not 1 <= month_int <= 12:
        raise RequestValidationError(errors=[{"msg": "Month must be 1-12"}])
    if month < sales_forecast_service.APP_ADOPTION_MONTH:
        raise RequestValidationError(errors=[{"msg": "Data not available before April 2025"}])
    return year_int, month_int


@router.get(
    "/reports/staff-performance-summary/",
    operation_id="accounting_reports_staff_performance_summary_retrieve",
    summary="Staff performance summary (all staff)",
    response=StaffPerformanceResponse,
    exclude_none=True,  # summary rows omit job_breakdown, as v1 did
)
def staff_performance_summary(
    request: HttpRequest, start_date: datetime.date, end_date: datetime.date
) -> staff_performance_service.StaffPerformanceData:
    """Billable utilisation and per-hour rates for every staff member."""
    _require_ordered(start_date, end_date)
    return staff_performance_service.get_staff_performance_data(start_date, end_date)


@router.get(
    "/reports/staff-performance/{staff_id}/",
    operation_id="accounting_reports_staff_performance_retrieve",
    summary="Staff performance detail (one staff member)",
    response=StaffPerformanceResponse,
    exclude_none=True,
)
def staff_performance_detail(
    request: HttpRequest,
    staff_id: uuid.UUID,
    start_date: datetime.date,
    end_date: datetime.date,
) -> staff_performance_service.StaffPerformanceData:
    """One staff member's metrics with the per-job breakdown."""
    _require_ordered(start_date, end_date)
    data = staff_performance_service.get_staff_performance_data(
        start_date, end_date, staff_id=str(staff_id)
    )
    if not data["staff"]:
        raise HttpError(404, f"No performance data found for staff ID: {staff_id}")
    return data


@router.get(
    "/reports/calendar/",
    operation_id="accounting_reports_calendar_retrieve",
    summary="KPI calendar data",
    response=KPICalendarResponse,
    exclude_none=True,  # holiday_name appears only on holidays, as v1 had it
)
def kpi_calendar(
    request: HttpRequest,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, object]:
    """Return the month's aggregated daily KPIs (defaults to the current month)."""
    today = timezone.localdate()
    year = year if year is not None else today.year
    month = month if month is not None else today.month
    # v1's explicit bounds, as request validation rather than a hand-built 400.
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise RequestValidationError(errors=[{"msg": "Year or month out of valid range."}])
    return kpi_service.get_calendar_data(year, month)


@router.get(
    "/reports/profit-and-loss/",
    operation_id="accounting_reports_profit_and_loss_retrieve",
    summary="Company profit and loss report",
    response={501: dict},
)
def profit_and_loss(request: HttpRequest) -> tuple[int, dict[str, str]]:
    """501 stub, exactly as v1 shipped: rebuilding against Xero is Phase 4."""
    raise HttpError(
        501,
        "Profit and Loss reporting is unavailable until it is rebuilt "
        "against the Xero Reports API.",
    )
