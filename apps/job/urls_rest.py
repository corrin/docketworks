from django.urls import path

from apps.job.views.data_integrity_views import DataIntegrityReportView
from apps.job.views.data_quality_report_views import ArchivedJobsComplianceView
from apps.job.views.delivery_docket_view import DeliveryDocketView
from apps.job.views.job_costing_views import JobCostSetView, JobQuoteRevisionView
from apps.job.views.job_costline_views import (
    CostLineApprovalView,
    CostLineCreateView,
    CostLineDeleteView,
    CostLineUpdateView,
)
from apps.job.views.job_delta_rejection_grouped_view import (
    JobDeltaRejectionGroupedListView,
    JobDeltaRejectionGroupedMarkResolvedView,
    JobDeltaRejectionGroupedMarkUnresolvedView,
)
from apps.job.views.job_file_detail_view import JobFileDetailView
from apps.job.views.job_file_thumbnail_view import JobFileThumbnailView
from apps.job.views.job_files_collection_view import JobFilesCollectionView
from apps.job.views.job_profitability_report_views import JobProfitabilityReportView
from apps.job.views.job_quote_chat_api import JobQuoteChatInteractionView
from apps.job.views.job_quote_chat_views import (
    JobQuoteChatHistoryView,
    JobQuoteChatMessageView,
)
from apps.job.views.job_rest_views import (
    JobBasicInformationRestView,
    JobCostSummaryRestView,
    JobCreateRestView,
    JobDeltaRejectionAdminRestView,
    JobDeltaRejectionListRestView,
    JobDetailRestView,
    JobEventListRestView,
    JobEventRestView,
    JobHeaderRestView,
    JobInvoicesRestView,
    JobQuoteAcceptRestView,
    JobQuoteRestView,
    JobStatusChoicesRestView,
    JobSummaryRestView,
    JobTimelineRestView,
    JobUndoChangeRestView,
    WeeklyMetricsRestView,
)
from apps.job.views.modern_timesheet_views import (
    ModernTimesheetDayView,
    ModernTimesheetEntryView,
    ModernTimesheetJobView,
)
from apps.job.views.month_end_rest_view import MonthEndRestView
from apps.job.views.quote_import_views import QuoteImportStatusView
from apps.job.views.quote_sync_views import (
    ApplyQuoteAPIView,
    LinkQuoteSheetAPIView,
    PreviewQuoteAPIView,
)
from apps.job.views.workshop_pdf_view import WorkshopPDFView

# URLs for new REST views
rest_urlpatterns = [
    # Job CRUD operations (REST style)
    path("jobs/", JobCreateRestView.as_view(), name="job_create_rest"),
    path("month-end/", MonthEndRestView.as_view(), name="month_end_rest"),
    path("jobs/<uuid:job_id>/", JobDetailRestView.as_view(), name="job_detail_rest"),
    path(
        "jobs/<uuid:job_id>/summary/",
        JobSummaryRestView.as_view(),
        name="job_summary_rest",
    ),
    path(
        "jobs/<uuid:job_id>/undo-change/",
        JobUndoChangeRestView.as_view(),
        name="job_undo_change_rest",
    ),
    # Job header (essential info only)
    path(
        "jobs/<uuid:job_id>/header/",
        JobHeaderRestView.as_view(),
        name="job_header_rest",
    ),
    # Job basic information (description, delivery date, order number, notes)
    path(
        "jobs/<uuid:job_id>/basic-info/",
        JobBasicInformationRestView.as_view(),
        name="job_basic_info_rest",
    ),
    # Job events (list)
    path(
        "jobs/<uuid:job_id>/events/",
        JobEventListRestView.as_view(),
        name="job_events_list_rest",
    ),
    # Job delta rejections (readonly)
    path(
        "jobs/<uuid:job_id>/delta-rejections/",
        JobDeltaRejectionListRestView.as_view(),
        name="job_delta_rejections_rest",
    ),
    path(
        "jobs/delta-rejections/grouped/",
        JobDeltaRejectionGroupedListView.as_view(),
        name="jobs-delta-rejections-grouped",
    ),
    path(
        "jobs/delta-rejections/grouped/mark_resolved/",
        JobDeltaRejectionGroupedMarkResolvedView.as_view(),
        name="jobs-delta-rejections-grouped-mark-resolved",
    ),
    path(
        "jobs/delta-rejections/grouped/mark_unresolved/",
        JobDeltaRejectionGroupedMarkUnresolvedView.as_view(),
        name="jobs-delta-rejections-grouped-mark-unresolved",
    ),
    path(
        "jobs/delta-rejections/",
        JobDeltaRejectionAdminRestView.as_view(),
        name="job_delta_rejections_admin_rest",
    ),
    # Job events (create)
    path(
        "jobs/<uuid:job_id>/events/create/",
        JobEventRestView.as_view(),
        name="job_events_rest",
    ),
    # Job timeline (unified events + cost lines)
    path(
        "jobs/<uuid:job_id>/timeline/",
        JobTimelineRestView.as_view(),
        name="job_timeline_rest",
    ),
    # Job invoices and quotes
    path(
        "jobs/<uuid:job_id>/invoices/",
        JobInvoicesRestView.as_view(),
        name="job_invoices_rest",
    ),
    path(
        "jobs/<uuid:job_id>/quote/",
        JobQuoteRestView.as_view(),
        name="job_quote_rest",
    ),
    # Job cost summary
    path(
        "jobs/<uuid:job_id>/costs/summary/",
        JobCostSummaryRestView.as_view(),
        name="job_cost_summary_rest",
    ),
    # Job status choices
    path(
        "jobs/status-choices/",
        JobStatusChoicesRestView.as_view(),
        name="job_status_choices_rest",
    ),
    # Quote acceptance endpoint
    path(
        "jobs/<uuid:job_id>/quote/accept/",
        JobQuoteAcceptRestView.as_view(),
        name="job_quote_accept_rest",
    ),
    # Job entries
    # Use CostLine endpoints instead of JobTimeEntryRestView,
    # JobMaterialEntryRestView, JobAdjustmentEntryRestView
    # Job costing
    path(
        "jobs/<uuid:pk>/cost_sets/<str:kind>/",
        JobCostSetView.as_view(),
        name="job_cost_set_rest",
    ),
    # Quote revision endpoint - creates new revision by archiving current data
    path(
        "jobs/<uuid:job_id>/cost_sets/quote/revise/",
        JobQuoteRevisionView.as_view(),
        name="job_quote_revision_rest",
    ),  # CostLine CRUD operations for modern timesheet
    path(
        "jobs/<uuid:job_id>/cost_sets/actual/cost_lines/",
        CostLineCreateView.as_view(),
        name="costline_create_rest",
    ),
    path(
        "jobs/<uuid:job_id>/cost_sets/<str:kind>/cost_lines/",
        CostLineCreateView.as_view(),
        name="costline_create_any_rest",
    ),
    path(
        "cost_lines/<str:cost_line_id>/",
        CostLineUpdateView.as_view(),
        name="costline_update_rest",
    ),
    path(
        "cost_lines/<str:cost_line_id>/delete/",
        CostLineDeleteView.as_view(),
        name="costline_delete_rest",
    ),
    path(
        "cost_lines/<str:cost_line_id>/approve/",
        CostLineApprovalView.as_view(),
        name="costline_approve_rest",
    ),
    # Modern Timesheet API endpoints
    path(
        "timesheet/entries/",
        ModernTimesheetEntryView.as_view(),
        name="modern_timesheet_entry_rest",
    ),
    path(
        "timesheet/staff/<uuid:staff_id>/date/<str:entry_date>/",
        ModernTimesheetDayView.as_view(),
        name="modern_timesheet_day_rest",
    ),
    path(
        "timesheet/jobs/<uuid:job_id>/",
        ModernTimesheetJobView.as_view(),
        name="modern_timesheet_job_rest",
    ),
    # Workshop PDF
    path(
        "jobs/<uuid:job_id>/workshop-pdf/",
        WorkshopPDFView.as_view(),
        name="workshop-pdf",
    ),
    # Delivery Docket PDF
    path(
        "jobs/<uuid:job_id>/delivery-docket/",
        DeliveryDocketView.as_view(),
        name="delivery-docket",
    ),
    # Job files - Collection operations (upload, list)
    path(
        "jobs/<uuid:job_id>/files/",
        JobFilesCollectionView.as_view(),
        name="job_files_collection",
    ),
    # Job files - Resource operations (download, update, delete)
    path(
        "jobs/<uuid:job_id>/files/<uuid:file_id>/",
        JobFileDetailView.as_view(),
        name="job_file_detail",
    ),
    # Job files - Thumbnail
    path(
        "jobs/<uuid:job_id>/files/<uuid:file_id>/thumbnail/",
        JobFileThumbnailView.as_view(),
        name="job_file_thumbnail",
    ),
    # Quote Import (NEW - Google Sheets sync)
    path(
        "jobs/<uuid:pk>/quote/link/",
        LinkQuoteSheetAPIView.as_view(),
        name="quote_link_sheet",
    ),
    path(
        "jobs/<uuid:pk>/quote/preview/",
        PreviewQuoteAPIView.as_view(),
        name="quote_preview",
    ),
    path(
        "jobs/<uuid:pk>/quote/apply/",
        ApplyQuoteAPIView.as_view(),
        name="quote_apply",
    ),
    path(
        "jobs/<uuid:job_id>/quote/status/",
        QuoteImportStatusView.as_view(),
        name="quote_import_status",
    ),
    # Weekly Metrics for WeeklyTimesheetView
    path(
        "jobs/weekly-metrics/",
        WeeklyMetricsRestView.as_view(),
        name="weekly_metrics_rest",
    ),
    # Job Quote Chat APIs
    path(
        "jobs/<uuid:job_id>/quote-chat/",
        JobQuoteChatHistoryView.as_view(),
        name="job_quote_chat_history",
    ),
    # AI-powered chat interaction (LLM call + tool execution)
    # Must be ABOVE the generic <message_id> route to avoid being
    # captured by it.
    path(
        "jobs/<uuid:job_id>/quote-chat/interaction/",
        JobQuoteChatInteractionView.as_view(),
        name="job_quote_chat_interaction",
    ),
    path(
        "jobs/<uuid:job_id>/quote-chat/<str:message_id>/",
        JobQuoteChatMessageView.as_view(),
        name="job_quote_chat_message",
    ),
    # Reports
    path(
        "reports/job-profitability/",
        JobProfitabilityReportView.as_view(),
        name="job_profitability_report",
    ),
    # Data Quality Reports
    path(
        "data-quality/archived-jobs-compliance/",
        ArchivedJobsComplianceView.as_view(),
        name="data_quality_archived_jobs_compliance",
    ),
    path(
        "data-integrity/scan/",
        DataIntegrityReportView.as_view(),
        name="data_integrity_scan",
    ),
]
