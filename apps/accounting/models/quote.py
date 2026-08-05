"""Xero quote model."""

import uuid
from typing import ClassVar

from django.db import models
from django.utils import timezone

from apps.accounting.enums import QuoteStatus


class Quote(models.Model):
    """A Xero quote, optionally linked one-to-one to a job."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    xero_id = models.UUIDField(unique=True)
    xero_tenant_id = models.CharField(  # noqa: DJ001
        max_length=255, null=True, blank=True
    )  # For reference only - we are not fully multi-tenant yet
    job = models.OneToOneField(
        "job.Job", on_delete=models.PROTECT, related_name="quote", null=True, blank=True
    )
    company = models.ForeignKey("company.Company", on_delete=models.PROTECT)
    date = models.DateField()
    status = models.CharField(max_length=50, choices=QuoteStatus.choices, default=QuoteStatus.DRAFT)
    total_excl_tax = models.DecimalField(max_digits=10, decimal_places=2)
    total_incl_tax = models.DecimalField(max_digits=10, decimal_places=2)
    xero_last_modified = models.DateTimeField(null=True, blank=True)
    xero_last_synced = models.DateTimeField(default=timezone.now)
    number = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    online_url = models.URLField(null=True, blank=True)  # noqa: DJ001
    raw_json = models.JSONField(null=True, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=~models.Q(number=""), name="number_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(online_url=""),
                name="accounting_quote_online_url_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="accounting_quote_xero_tenant_id_not_blank",
            ),
        ]

    def __str__(self) -> str:
        job_info = f"{self.job.job_number}" if self.job else "No Job"
        return f"Quote ({self.status}) for Job {job_info}"
