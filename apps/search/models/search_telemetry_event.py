"""Search telemetry model, ported from v1 ``apps/workflow/models/search_telemetry_event.py``."""

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone


class SearchTelemetryEvent(models.Model):
    """Search/click telemetry shared by company, Kanban, and stock search."""

    class EventType(models.TextChoices):
        """Kind of telemetry event recorded."""

        SEARCH = "search", "Search"
        CLICK = "click", "Click"

    class Domain(models.TextChoices):
        """Search domain the event belongs to."""

        COMPANY = "company", "Company"
        KANBAN = "kanban", "Kanban"
        STOCK = "stock", "Stock"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    domain = models.CharField(max_length=20, choices=Domain.choices)
    source = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001
    query = models.CharField(max_length=255, blank=True, null=True)  # noqa: DJ001
    normalized_query = models.CharField(max_length=255, blank=True, null=True)  # noqa: DJ001
    filters = models.JSONField(default=dict, blank=True)
    result_count = models.PositiveIntegerField(default=0)
    returned_count = models.PositiveIntegerField(default=0)
    returned_result_ids = models.JSONField(default=list, blank=True)
    selected_result_id = models.CharField(max_length=255, blank=True, null=True)  # noqa: DJ001
    selected_label = models.CharField(max_length=255, blank=True, null=True)  # noqa: DJ001
    selected_rank = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    source_event_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="search_telemetry_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workflow_searchtelemetryevent"  # v1 home was the workflow app
        ordering: ClassVar[list[str]] = ["-occurred_at", "-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["domain", "event_type", "-occurred_at"],
                name="wf_search_domain_event_idx",
            ),
            models.Index(
                fields=["domain", "normalized_query", "-occurred_at"],
                name="wf_search_domain_query_idx",
            ),
            models.Index(
                fields=["source", "-occurred_at"],
                name="workflow_search_source_idx",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(normalized_query=""), name="normalized_query_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(query=""), name="query_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(selected_label=""), name="selected_label_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(selected_result_id=""), name="selected_result_id_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(source_event_hash=""), name="source_event_hash_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(source=""), name="source_not_blank"),
        ]

    def __str__(self) -> str:
        return f"{self.domain}:{self.event_type}:{self.query}"
