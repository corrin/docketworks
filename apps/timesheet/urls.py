"""
Timesheet URLs - Single Source of Truth

Consolidated URL configuration for all timesheet functionality:
- Modern REST API endpoints using CostLine architecture
- Clean, consistent URL structure
"""

from django.urls import path

from .api.daily_timesheet_views import (
    DailyTimesheetSummaryAPIView,
    StaffDailyDetailAPIView,
)
from .views.api import (
    CreatePayRunAPIView,
    JobsAPIView,
    PayRunListAPIView,
    PostWeekToXeroPayrollAPIView,
    RefreshPayRunsAPIView,
    StaffListAPIView,
    WeeklyTimesheetAPIView,
    stream_payroll_post,
)

app_name = "timesheet"

urlpatterns = [
    # ===== REST API ENDPOINTS (Modern - Vue.js Frontend) =====
    # Staff endpoints
    path("staff/", StaffListAPIView.as_view(), name="api_staff_list"),
    # Daily timesheet endpoints - using DailyTimesheetService (CostLine-based)
    path(
        "daily/<str:target_date>/",
        DailyTimesheetSummaryAPIView.as_view(),
        name="api_daily_summary",
    ),
    path(
        "staff/<str:staff_id>/daily/<str:target_date>/",
        StaffDailyDetailAPIView.as_view(),
        name="api_staff_daily_detail",
    ),
    # Weekly timesheet endpoints - using WeeklyTimesheetService (CostLine-based)
    path("weekly/", WeeklyTimesheetAPIView.as_view(), name="api_weekly_timesheet"),
    # Jobs endpoints
    path("jobs/", JobsAPIView.as_view(), name="api_jobs_list"),
    # Xero Payroll endpoints
    path(
        "payroll/pay-runs/refresh",
        RefreshPayRunsAPIView.as_view(),
        name="api_refresh_pay_runs",
    ),
    path(
        "payroll/pay-runs/create",
        CreatePayRunAPIView.as_view(),
        name="api_create_pay_run",
    ),
    path(
        "payroll/pay-runs/",
        PayRunListAPIView.as_view(),
        name="api_list_pay_runs",
    ),
    path(
        "payroll/post-staff-week/",
        PostWeekToXeroPayrollAPIView.as_view(),
        name="api_post_staff_week",
    ),
    path(
        "payroll/post-staff-week/stream/<str:task_id>/",
        stream_payroll_post,
        name="api_post_staff_week_stream",
    ),
]
