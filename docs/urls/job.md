# Job URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### Company_Defaults Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/company_defaults/` | `job_rest_views.get_company_defaults_api` | `jobs:company_defaults_api` | API endpoint to fetch company default settings. |

### Cost_Lines Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/cost_lines/<str:cost_line_id>/` | `job_costline_views.CostLineUpdateView` | `jobs:costline_update_rest` | Update an existing CostLine |
| `/cost_lines/<str:cost_line_id>/approve/` | `job_costline_views.CostLineApprovalView` | `jobs:costline_approve_rest` | Approve an existing CostLine |
| `/cost_lines/<str:cost_line_id>/delete/` | `job_costline_views.CostLineDeleteView` | `jobs:costline_delete_rest` | Delete an existing CostLine |

### Data-Integrity Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/data-integrity/scan/` | `data_integrity_views.DataIntegrityReportView` | `jobs:data_integrity_scan` | API view for comprehensive database integrity checking |

### Data-Quality Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/data-quality/archived-jobs-compliance/` | `data_quality_report_views.ArchivedJobsComplianceView` | `jobs:data_quality_archived_jobs_compliance` | API view for checking archived jobs compliance. |

### Job Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/job/<uuid:job_id>/assignment/` | `assign_job_view.JobAssignmentCreateView` | `jobs:api_job_assignment` | API Endpoint to assign staff to a job (POST /api/job/<job_id>/assignment) |
| `/job/<uuid:job_id>/assignment/<uuid:staff_id>/` | `assign_job_view.JobAssignmentDeleteView` | `jobs:api_job_assignment_staff` | API Endpoint to remove staff from a job (DELETE /api/job/<job_id>/assignment/<staff_id>) |
| `/job/completed/` | `archive_completed_jobs_view.ArchiveCompleteJobsListAPIView` | `jobs:api_jobs_completed` | API Endpoint to provide Job data for archiving display |
| `/job/completed/archive/` | `archive_completed_jobs_view.ArchiveCompleteJobsAPIView` | `jobs:api_jobs_archive` | API Endpoint to set 'paid' flag as True in the received jobs |

### Jobs Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/jobs/` | `job_rest_views.JobCreateRestView` | `jobs:job_create_rest` | REST view for Job creation. |
| `/jobs/<str:job_id>/update-status/` | `kanban_view_api.UpdateJobStatusAPIView` | `jobs:api_update_job_status` | Update job status - API endpoint. |
| `/jobs/<uuid:job_id>/` | `job_rest_views.JobDetailRestView` | `jobs:job_detail_rest` | REST view for CRUD operations on a specific Job. |
| `/jobs/<uuid:job_id>/basic-info/` | `job_rest_views.JobBasicInformationRestView` | `jobs:job_basic_info_rest` | REST view for Job basic information. |
| `/jobs/<uuid:job_id>/cost_sets/<str:kind>/cost_lines/` | `job_costline_views.CostLineCreateView` | `jobs:costline_create_any_rest` | Create a new CostLine in the specified job's CostSet |
| `/jobs/<uuid:job_id>/cost_sets/actual/cost_lines/` | `job_costline_views.CostLineCreateView` | `jobs:costline_create_rest` | Create a new CostLine in the specified job's CostSet |
| `/jobs/<uuid:job_id>/cost_sets/quote/revise/` | `job_costing_views.JobQuoteRevisionView` | `jobs:job_quote_revision_rest` | Manage quote revisions for jobs. |
| `/jobs/<uuid:job_id>/costs/summary/` | `job_rest_views.JobCostSummaryRestView` | `jobs:job_cost_summary_rest` | REST view for Job cost summary. |
| `/jobs/<uuid:job_id>/delivery-docket/` | `delivery_docket_view.DeliveryDocketView` | `jobs:delivery-docket` | API view for generating and serving delivery docket PDFs. |
| `/jobs/<uuid:job_id>/delta-rejections/` | `job_rest_views.JobDeltaRejectionListRestView` | `jobs:job_delta_rejections_rest` | REST view that returns delta rejections for a specific job. |
| `/jobs/<uuid:job_id>/events/` | `job_rest_views.JobEventListRestView` | `jobs:job_events_list_rest` | REST view for Job events list. |
| `/jobs/<uuid:job_id>/events/create/` | `job_rest_views.JobEventRestView` | `jobs:job_events_rest` | REST view for Job events. |
| `/jobs/<uuid:job_id>/files/` | `job_files_collection_view.JobFilesCollectionView` | `jobs:job_files_collection` | Collection operations on job files. |
| `/jobs/<uuid:job_id>/files/<uuid:file_id>/` | `job_file_detail_view.JobFileDetailView` | `jobs:job_file_detail` | Resource operations on individual job files. |
| `/jobs/<uuid:job_id>/files/<uuid:file_id>/thumbnail/` | `job_file_thumbnail_view.JobFileThumbnailView` | `jobs:job_file_thumbnail` | Thumbnail serving for job files. |
| `/jobs/<uuid:job_id>/header/` | `job_rest_views.JobHeaderRestView` | `jobs:job_header_rest` | REST view for Job header information. |
| `/jobs/<uuid:job_id>/invoices/` | `job_rest_views.JobInvoicesRestView` | `jobs:job_invoices_rest` | REST view for Job invoices. |
| `/jobs/<uuid:job_id>/quote-chat/` | `job_quote_chat_views.JobQuoteChatHistoryView` | `jobs:job_quote_chat_history` | REST view for getting and managing chat history for a job. |
| `/jobs/<uuid:job_id>/quote-chat/<str:message_id>/` | `job_quote_chat_views.JobQuoteChatMessageView` | `jobs:job_quote_chat_message` | REST view for updating individual chat messages. |
| `/jobs/<uuid:job_id>/quote-chat/interaction/` | `job_quote_chat_api.JobQuoteChatInteractionView` | `jobs:job_quote_chat_interaction` | API view to handle real-time interaction with the AI chat assistant. |
| `/jobs/<uuid:job_id>/quote/` | `job_rest_views.JobQuoteRestView` | `jobs:job_quote_rest` | REST view for Job quotes. |
| `/jobs/<uuid:job_id>/quote/accept/` | `job_rest_views.JobQuoteAcceptRestView` | `jobs:job_quote_accept_rest` | REST view for accepting job quotes. |
| `/jobs/<uuid:job_id>/quote/status/` | `quote_import_views.QuoteImportStatusView` | `jobs:quote_import_status` | Get current quote import status and latest quote information. |
| `/jobs/<uuid:job_id>/reorder/` | `kanban_view_api.ReorderJobAPIView` | `jobs:api_reorder_job` | Reorder job within or between columns - API endpoint. |
| `/jobs/<uuid:job_id>/summary/` | `job_rest_views.JobSummaryRestView` | `jobs:job_summary_rest` | REST view for Job summary data (no cost lines or events). |
| `/jobs/<uuid:job_id>/timeline/` | `job_rest_views.JobTimelineRestView` | `jobs:job_timeline_rest` | REST view for unified Job timeline. |
| `/jobs/<uuid:job_id>/undo-change/` | `job_rest_views.JobUndoChangeRestView` | `jobs:job_undo_change_rest` | Undo a previously applied job delta. |
| `/jobs/<uuid:job_id>/workshop-pdf/` | `workshop_pdf_view.WorkshopPDFView` | `jobs:workshop-pdf` | API view for generating and serving workshop PDF documents for jobs. |
| `/jobs/<uuid:pk>/cost_sets/<str:kind>/` | `job_costing_views.JobCostSetView` | `jobs:job_cost_set_rest` | Retrieve the latest CostSet for a specific job and kind. |
| `/jobs/<uuid:pk>/quote/apply/` | `quote_sync_views.ApplyQuoteAPIView` | `jobs:quote_apply` | Apply quote import from linked Google Sheet. |
| `/jobs/<uuid:pk>/quote/link/` | `quote_sync_views.LinkQuoteSheetAPIView` | `jobs:quote_link_sheet` | Link a job to a Google Sheets quote template. |
| `/jobs/<uuid:pk>/quote/preview/` | `quote_sync_views.PreviewQuoteAPIView` | `jobs:quote_preview` | Preview quote import from linked Google Sheet. |
| `/jobs/advanced-search/` | `kanban_view_api.AdvancedSearchAPIView` | `jobs:api_advanced_search` | Endpoint for advanced job search - API endpoint. |
| `/jobs/delta-rejections/` | `job_rest_views.JobDeltaRejectionAdminRestView` | `jobs:job_delta_rejections_admin_rest` | Global listing of delta rejections for admin/monitoring usage. |
| `/jobs/fetch-all/` | `kanban_view_api.FetchAllJobsAPIView` | `jobs:api_fetch_all_jobs` | Fetch all jobs for Kanban board - API endpoint. |
| `/jobs/fetch-by-column/<str:column_id>/` | `kanban_view_api.FetchJobsByColumnAPIView` | `jobs:api_fetch_jobs_by_column` | Fetch jobs by kanban column using new categorization system. |
| `/jobs/fetch/<str:status>/` | `kanban_view_api.FetchJobsAPIView` | `jobs:api_fetch_jobs` | Fetch jobs by status with optional search - API endpoint. |
| `/jobs/status-choices/` | `job_rest_views.JobStatusChoicesRestView` | `jobs:job_status_choices_rest` | REST view for Job status choices. |
| `/jobs/status-values/` | `kanban_view_api.FetchStatusValuesAPIView` | `jobs:api_fetch_status_values` | Return available status values for Kanban - API endpoint. |
| `/jobs/weekly-metrics/` | `job_rest_views.WeeklyMetricsRestView` | `jobs:weekly_metrics_rest` | REST view for fetching weekly metrics. |
| `/jobs/workshop/` | `workshop_view.WorkshopKanbanView` | `jobs:api_workshop_kanban` | No description available |

### Month-End Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/month-end/` | `month_end_rest_view.MonthEndRestView` | `jobs:month_end_rest` | REST API view for month-end processing of special jobs and stock data. |

### Reports
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/reports/job-aging/` | `job_aging_view.JobAgingAPIView` | `accounting:api_job_aging` | API Endpoint to provide job aging data with financial and timing information |
| `/reports/job-movement/` | `JobMovementMetricsView` | `accounting:api_job_movement` | API endpoint for job movement and conversion metrics. |
| `/reports/job-profitability/` | `job_profitability_report_views.JobProfitabilityReportView` | `jobs:job_profitability_report` | API view for job profitability reporting. |

### Timesheet Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/timesheet/entries/` | `modern_timesheet_views.ModernTimesheetEntryView` | `jobs:modern_timesheet_entry_rest` | Modern timesheet entry management using CostLine architecture |
| `/timesheet/jobs/<uuid:job_id>/` | `modern_timesheet_views.ModernTimesheetJobView` | `jobs:modern_timesheet_job_rest` | Get timesheet entries for a specific job |
| `/timesheet/staff/<uuid:staff_id>/date/<str:entry_date>/` | `modern_timesheet_views.ModernTimesheetDayView` | `jobs:modern_timesheet_day_rest` | Get timesheet entries for a specific day and staff |

### Workshop Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/workshop/timesheets/` | `workshop_view.WorkshopTimesheetView` | `jobs:api_workshop_timesheets` | API for workshop staff to manage their own timesheet entries (CostLines). |
