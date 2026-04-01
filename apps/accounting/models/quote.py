import uuid

from django.db import models
from django.utils import timezone

from apps.accounting.enums import QuoteStatus


class Quote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    xero_id = models.UUIDField(unique=True)
    xero_tenant_id = models.CharField(
        max_length=255, null=True, blank=True
    )  # For reference only - we are not fully multi-tenant yet
    job = models.OneToOneField(
        "job.Job", on_delete=models.PROTECT, related_name="quote", null=True, blank=True
    )
    client = models.ForeignKey("client.Client", on_delete=models.PROTECT)
    date = models.DateField()
    status = models.CharField(
        max_length=50, choices=QuoteStatus.choices, default=QuoteStatus.DRAFT
    )
    total_excl_tax = models.DecimalField(max_digits=10, decimal_places=2)
    total_incl_tax = models.DecimalField(max_digits=10, decimal_places=2)
    xero_last_modified = models.DateTimeField(null=True, blank=True)
    xero_last_synced = models.DateTimeField(default=timezone.now)
    number = models.CharField(max_length=255, null=True, blank=True)
    online_url = models.URLField(null=True, blank=True)
    raw_json = models.JSONField(null=True, blank=True)

    def __str__(self) -> str:
        job_info = f"{self.job.job_number}" if self.job else "No Job"
        return f"Quote ({self.status}) for Job {job_info}"
