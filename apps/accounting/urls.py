from django.urls import path

from apps.accounting.views import JobAgingAPIView
from apps.accounting.views.kpi_view import KPICalendarAPIView, KPICalendarTemplateView
from apps.accounting.views.rdti_spend_view import RDTISpendAPIView
from apps.accounting.views.sales_forecast_view import (
    SalesForecastAPIView,
    SalesForecastMonthDetailAPIView,
    SalesForecastTemplateView,
)
from apps.accounting.views.staff_performance_views import (
    StaffPerformanceDetailAPIView,
    StaffPerformanceSummaryAPIView,
    StaffPerformanceTemplateView,
)
from apps.workflow.api.reports import CompanyProfitAndLossReport, JobMovementMetricsView
from apps.workflow.api.reports.payroll_reconciliation import (
    PayrollDateRangeView,
    PayrollReconciliationReport,
)

app_name = "accounting"


urlpatterns = [
    path(
        "api/reports/calendar/",
        KPICalendarAPIView.as_view(),
        name="api_kpi_calendar",
    ),
    path(
        "api/reports/job-aging/",
        JobAgingAPIView.as_view(),
        name="api_job_aging",
    ),
    path(
        "api/reports/job-movement/",
        JobMovementMetricsView.as_view(),
        name="api_job_movement",
    ),
    path(
        "api/reports/payroll-date-range/",
        PayrollDateRangeView.as_view(),
        name="api_payroll_date_range",
    ),
    path(
        "api/reports/payroll-reconciliation/",
        PayrollReconciliationReport.as_view(),
        name="api_payroll_reconciliation",
    ),
    path(
        "api/reports/profit-and-loss/",
        CompanyProfitAndLossReport.as_view(),
        name="api_profit_and_loss",
    ),
    path(
        "api/reports/sales-forecast/",
        SalesForecastAPIView.as_view(),
        name="api_sales_forecast",
    ),
    path(
        "api/reports/sales-forecast/<str:month>/",
        SalesForecastMonthDetailAPIView.as_view(),
        name="api_sales_forecast_month_detail",
    ),
    path(
        "api/reports/staff-performance-summary/",
        StaffPerformanceSummaryAPIView.as_view(),
        name="api_staff_performance_summary",
    ),
    path(
        "api/reports/staff-performance/<uuid:staff_id>/",
        StaffPerformanceDetailAPIView.as_view(),
        name="api_staff_performance_detail",
    ),
    path(
        "api/reports/rdti-spend/",
        RDTISpendAPIView.as_view(),
        name="api_rdti_spend",
    ),
    path(
        "reports/calendar/",
        KPICalendarTemplateView.as_view(),
        name="kpi_calendar",
    ),
    path(
        "reports/sales-forecast/",
        SalesForecastTemplateView.as_view(),
        name="sales_forecast",
    ),
    path(
        "reports/staff-performance/",
        StaffPerformanceTemplateView.as_view(),
        name="staff_performance",
    ),
]
