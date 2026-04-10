# Accounting URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### Reports
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/reports/calendar/` | `kpi_view.KPICalendarAPIView` | `accounting:api_kpi_calendar` | API Endpoint to provide KPI data for calendar display |
| `/reports/job-aging/` | `job_aging_view.JobAgingAPIView` | `accounting:api_job_aging` | API Endpoint to provide job aging data with financial and timing information |
| `/reports/rdti-spend/` | `rdti_spend_view.RDTISpendAPIView` | `accounting:api_rdti_spend` | API endpoint for the RDTI spend report. |
| `/reports/sales-forecast/` | `sales_forecast_view.SalesForecastAPIView` | `accounting:api_sales_forecast` | API Endpoint to compare monthly sales between Xero and Job Manager. |
| `/reports/sales-forecast/<str:month>/` | `sales_forecast_view.SalesForecastMonthDetailAPIView` | `accounting:api_sales_forecast_month_detail` | API Endpoint to drill down into a specific month's sales data. |
| `/reports/staff-performance-summary/` | `staff_performance_views.StaffPerformanceSummaryAPIView` | `accounting:api_staff_performance_summary` | API endpoint for staff performance summary (all staff) |
| `/reports/staff-performance/<uuid:staff_id>/` | `staff_performance_views.StaffPerformanceDetailAPIView` | `accounting:api_staff_performance_detail` | API endpoint for individual staff performance detail |
| `/reports/wip/` | `wip_view.WIPReportAPIView` | `accounting:api_wip_report` | API endpoint for Work In Progress report. |
