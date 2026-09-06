"""The record of what this install spends reaching external vendors."""

import uuid
from typing import ClassVar

from django.db import models
from django.utils import timezone


class VendorCall(models.Model):
    """One row is one call to an external vendor.

    The row carries what that call consumed and what the vendor said remained
    afterwards. Nothing here is a total: rolling-window, per-endpoint and
    per-run views are queries over these rows, so the grain never has to be
    guessed in advance. A daily per-endpoint counter was the alternative
    (proposed in 9c4eddb); it was rejected because the bucket it aggregates
    into is a calendar day while Xero's limit is a rolling 24 hours, so the
    counter cannot answer the operational question.

    No pruning task, weighed against ADR 0047's "it buys a table and a
    retention question": the vendors bound the row rate themselves. Xero
    cannot produce more than the 5,000/day quota being measured, and the other
    seams run far below that, so the ceiling is ~1.8M narrow rows a year.
    """

    class Vendor(models.TextChoices):
        """The external system reached, one value per seam in ``conftest.py``."""

        XERO = "xero", "Xero"
        XERO_TOKEN = "xero_token", "Xero token endpoint"
        LLM = "llm", "LLM gateway"
        MAPS = "maps", "Google Maps"
        PHONE = "phone", "Phone provider"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.CharField(max_length=20, choices=Vendor.choices)
    method = models.CharField(max_length=10)
    # Path only. The query string carries ids and cursors, which would split
    # one endpoint into thousands of distinct values and defeat the grouping
    # these rows exist to support.
    endpoint = models.CharField(max_length=255)
    occurred_at = models.DateTimeField(default=timezone.now)
    duration_ms = models.PositiveIntegerField()

    # Null where the vendor reports no such meter: the LLM gateway hands back
    # no HTTP status, and only Xero returns remaining-quota headers.
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    day_remaining = models.IntegerField(null=True, blank=True)
    minute_remaining = models.IntegerField(null=True, blank=True)
    tokens_in = models.PositiveIntegerField(null=True, blank=True)
    tokens_out = models.PositiveIntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    model_name = models.CharField(  # noqa: DJ001 -- NULL means "not an LLM call" (ADR 0040)
        max_length=100, null=True, blank=True
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-occurred_at"]
        indexes: ClassVar[list[models.Index]] = [
            # Serves both the rolling-window rollups and the newest-row lookup
            # that quota_floor_breached does on every sync page.
            models.Index(fields=["vendor", "-occurred_at"], name="vendorcall_vendor_time_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(model_name=""), name="vendorcall_model_name_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(method=""), name="vendorcall_method_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(endpoint=""), name="vendorcall_endpoint_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.vendor} {self.method} {self.endpoint} @ {self.occurred_at.isoformat()}"
