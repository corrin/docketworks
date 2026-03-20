"""
URL Configuration for Job App

This module contains all URL patterns related to job management:
- Job CRUD operations
- Job events
- Job files
- Job status management
- etc.
"""

from django.urls import path

from apps.job.urls_rest import rest_urlpatterns
from apps.job.views import (
    ArchiveCompleteJobsViews,
    JobAssignmentCreateView,
    JobAssignmentDeleteView,
    kanban_view_api,
    workshop_view,
)
from apps.job.views.job_rest_views import get_company_defaults_api

app_name = "jobs"


urlpatterns = [
    path(
        "job/completed/",
        ArchiveCompleteJobsViews.ArchiveCompleteJobsListAPIView.as_view(),
        name="api_jobs_completed",
    ),
    path(
        "job/completed/archive",
        ArchiveCompleteJobsViews.ArchiveCompleteJobsAPIView.as_view(),
        name="api_jobs_archive",
    ),
    path(
        "job/<uuid:job_id>/assignment",
        JobAssignmentCreateView.as_view(),
        name="api_job_assignment",
    ),
    path(
        "job/<uuid:job_id>/assignment/<uuid:staff_id>",
        JobAssignmentDeleteView.as_view(),
        name="api_job_assignment_staff",
    ),
    path(
        "company_defaults/",
        get_company_defaults_api,
        name="company_defaults_api",
    ),
    # New Kanban API endpoints
    path(
        "jobs/fetch-all/",
        kanban_view_api.FetchAllJobsAPIView.as_view(),
        name="api_fetch_all_jobs",
    ),
    path(
        "jobs/workshop",
        workshop_view.WorkshopKanbanView.as_view(),
        name="api_workshop_kanban",
    ),
    path(
        "workshop/timesheets/",
        workshop_view.WorkshopTimesheetView.as_view(),
        name="api_workshop_timesheets",
    ),
    path(
        "jobs/<str:job_id>/update-status/",
        kanban_view_api.UpdateJobStatusAPIView.as_view(),
        name="api_update_job_status",
    ),
    path(
        "jobs/<uuid:job_id>/reorder/",
        kanban_view_api.ReorderJobAPIView.as_view(),
        name="api_reorder_job",
    ),
    path(
        "jobs/fetch/<str:status>/",
        kanban_view_api.FetchJobsAPIView.as_view(),
        name="api_fetch_jobs",
    ),
    path(
        "jobs/fetch-by-column/<str:column_id>/",
        kanban_view_api.FetchJobsByColumnAPIView.as_view(),
        name="api_fetch_jobs_by_column",
    ),
    path(
        "jobs/status-values/",
        kanban_view_api.FetchStatusValuesAPIView.as_view(),
        name="api_fetch_status_values",
    ),
    path(
        "jobs/advanced-search/",
        kanban_view_api.AdvancedSearchAPIView.as_view(),
        name="api_advanced_search",
    ),
]

urlpatterns += rest_urlpatterns
