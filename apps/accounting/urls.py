from django.urls import path

from apps.accounting.views import JobAgingAPIView
from apps.accounting.views.kpi_view import KPICalendarAPIView
from apps.accounting.views.rdti_spend_view import RDTISpendAPIView
from apps.accounting.views.sales_forecast_view import (
    SalesForecastAPIView,
    SalesForecastMonthDetailAPIView,
)
from apps.accounting.views.staff_performance_views import (
    StaffPerformanceDetailAPIView,
    StaffPerformanceSummaryAPIView,
)
from apps.workflow.api.reports import CompanyProfitAndLossReport, JobMovementMetricsView
from apps.workflow.api.reports.payroll_reconciliation import (
    PayrollDateRangeView,
    PayrollReconciliationReport,
)

app_name = "accounting"


urlpatterns = [
    path(
        "reports/calendar/",
        KPICalendarAPIView.as_view(),
        name="api_kpi_calendar",
    ),
    path(
        "reports/job-aging/",
        JobAgingAPIView.as_view(),
        name="api_job_aging",
    ),
    path(
        "reports/job-movement/",
        JobMovementMetricsView.as_view(),
        name="api_job_movement",
    ),
    path(
        "reports/payroll-date-range/",
        PayrollDateRangeView.as_view(),
        name="api_payroll_date_range",
    ),
    path(
        "reports/payroll-reconciliation/",
        PayrollReconciliationReport.as_view(),
        name="api_payroll_reconciliation",
    ),
    path(
        "reports/profit-and-loss/",
        CompanyProfitAndLossReport.as_view(),
        name="api_profit_and_loss",
    ),
    path(
        "reports/sales-forecast/",
        SalesForecastAPIView.as_view(),
        name="api_sales_forecast",
    ),
    path(
        "reports/sales-forecast/<str:month>/",
        SalesForecastMonthDetailAPIView.as_view(),
        name="api_sales_forecast_month_detail",
    ),
    path(
        "reports/staff-performance-summary/",
        StaffPerformanceSummaryAPIView.as_view(),
        name="api_staff_performance_summary",
    ),
    path(
        "reports/staff-performance/<uuid:staff_id>/",
        StaffPerformanceDetailAPIView.as_view(),
        name="api_staff_performance_detail",
    ),
    path(
        "reports/rdti-spend/",
        RDTISpendAPIView.as_view(),
        name="api_rdti_spend",
    ),
]
