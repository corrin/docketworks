import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class SearchTelemetryEvent(models.Model):
    """Search/click telemetry shared by company, Kanban, and stock search."""

    class EventType(models.TextChoices):
        SEARCH = "search", "Search"
        CLICK = "click", "Click"

    class Domain(models.TextChoices):
        CLIENT = "client", "Client"
        KANBAN = "kanban", "Kanban"
        STOCK = "stock", "Stock"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    domain = models.CharField(max_length=20, choices=Domain.choices)
    source = models.CharField(max_length=100, blank=True)
    query = models.CharField(max_length=255, blank=True)
    normalized_query = models.CharField(max_length=255, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    result_count = models.PositiveIntegerField(default=0)
    returned_count = models.PositiveIntegerField(default=0)
    returned_result_ids = models.JSONField(default=list, blank=True)
    selected_result_id = models.CharField(max_length=255, blank=True)
    selected_label = models.CharField(max_length=255, blank=True)
    selected_rank = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    source_event_hash = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
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
        ordering = ["-occurred_at", "-created_at"]
        indexes = [
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

    def __str__(self):
        return f"{self.domain}:{self.event_type}:{self.query}"
