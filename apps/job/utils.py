"""Utility functions for job-related operations."""

from django.db import models

from apps.job.models import Job


def get_active_jobs() -> models.QuerySet[Job]:
    """
    Returns a queryset of Jobs considered active for work or resource assignment
    (e.g., time entry, stock allocation).

    Excludes jobs that are rejected, on hold, completed, or archived.
    This matches the filter used in the TimesheetEntryView.
    """
    excluded_statuses = ["rejected", "on_hold", "archived"]
    # Include select_related for fields commonly needed when displaying these jobs
    return Job.objects.exclude(status__in=excluded_statuses).select_related("client")
