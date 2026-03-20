# Timesheet URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### Daily Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/daily/<str:target_date>/` | `daily_timesheet_views.DailyTimesheetSummaryAPIView` | `timesheet:api_daily_summary` | Get daily timesheet summary for all staff |

### Jobs Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/jobs/` | `api.JobsAPIView` | `timesheet:api_jobs_list` | API endpoint to get available jobs for timesheet entries. |

### Payroll Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/payroll/pay-runs/` | `api.PayRunListAPIView` | `timesheet:api_list_pay_runs` | API endpoint to list all pay runs for the configured payroll calendar. |
| `/payroll/pay-runs/create/` | `api.CreatePayRunAPIView` | `timesheet:api_create_pay_run` | API endpoint to create a pay run in Xero Payroll. |
| `/payroll/pay-runs/refresh/` | `api.RefreshPayRunsAPIView` | `timesheet:api_refresh_pay_runs` | API endpoint to refresh cached pay runs from Xero. |
| `/payroll/post-staff-week/` | `api.PostWeekToXeroPayrollAPIView` | `timesheet:api_post_staff_week` | API endpoint to start posting weekly timesheets to Xero Payroll. |
| `/payroll/post-staff-week/stream/<str:task_id>/` | `api.stream_payroll_post` | `timesheet:api_post_staff_week_stream` | SSE endpoint to stream payroll posting progress. |

### Staff Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/staff/` | `api.StaffListAPIView` | `timesheet:api_staff_list` | API endpoint to get filtered list of staff members for timesheet operations. |
| `/staff/<str:staff_id>/daily/<str:target_date>/` | `daily_timesheet_views.StaffDailyDetailAPIView` | `timesheet:api_staff_daily_detail` | Get detailed timesheet data for a specific staff member |

### Timesheet Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/timesheet/entries/` | `modern_timesheet_views.ModernTimesheetEntryView` | `jobs:modern_timesheet_entry_rest` | Modern timesheet entry management using CostLine architecture |
| `/timesheet/jobs/<uuid:job_id>/` | `modern_timesheet_views.ModernTimesheetJobView` | `jobs:modern_timesheet_job_rest` | Get timesheet entries for a specific job |
| `/timesheet/staff/<uuid:staff_id>/date/<str:entry_date>/` | `modern_timesheet_views.ModernTimesheetDayView` | `jobs:modern_timesheet_day_rest` | Get timesheet entries for a specific day and staff |

### Weekly Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/weekly/` | `api.WeeklyTimesheetAPIView` | `timesheet:api_weekly_timesheet` | Comprehensive weekly timesheet API endpoint using WeeklyTimesheetService. |
