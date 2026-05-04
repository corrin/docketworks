"""Read-only ViewSets exposing the Celery Beat schedule + task execution history.

Replaces views_django_jobs.py — same visibility surface, backed by
django-celery-beat / django-celery-results. Management actions
(create/update/delete/run-now) are intentionally out of scope; operators use
Django admin (`/admin/django_celery_beat/periodictask/`) until Trello #297
ships the in-app management UI.
"""

from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.job.permissions import IsOfficeStaff
from apps.workflow.api.pagination import FiftyPerPagePagination

from .serializers_scheduled_tasks import (
    ScheduledTaskExecutionSerializer,
    ScheduledTaskSerializer,
)


class ScheduledTaskViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PeriodicTask.objects.all().order_by("name")
    serializer_class = ScheduledTaskSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    pagination_class = FiftyPerPagePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "task"]


class ScheduledTaskExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    """Beat-fired task executions only.

    Exclude TaskResult rows whose `periodic_task_name` is empty — those are
    ad-hoc Celery work (webhook handlers, health checks, etc.) which would
    otherwise drown out the scheduled-task history this view is for.
    """

    queryset = (
        TaskResult.objects.exclude(periodic_task_name__isnull=True)
        .exclude(periodic_task_name="")
        .order_by("-date_done")
    )
    serializer_class = ScheduledTaskExecutionSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    pagination_class = FiftyPerPagePagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["task_name", "periodic_task_name", "status"]
