import uuid

from django.db import models

from apps.accounts.models import Staff


class JobCompletionChecklist(models.Model):
    """Staff confirmations recorded while finishing a job.

    Deliberately advisory: nothing here blocks invoicing, changes job status,
    creates tasks, or nags. Its only job is to remember what a staff member
    confirmed, and to leave an audit trail when a confirmation is withdrawn.

    ``updated_at`` and ``updated_by`` are NULL until the first confirmation is
    recorded — a row can exist with nothing yet confirmed.
    """

    # The confirmable items, in display order. Serializers and the update
    # service derive their accepted keys from this tuple, so adding an item here
    # is the only change needed to expose it.
    ITEM_FIELDS = (
        "time_entries_complete",
        "materials_complete",
        "customer_approval_confirmed",
    )

    # Item key → the label used in job-history events.
    ITEM_LABELS = {
        "time_entries_complete": "All time entered",
        "materials_complete": "All materials entered",
        "customer_approval_confirmed": "Customer approval confirmed",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        "job.Job",
        on_delete=models.CASCADE,
        related_name="completion_checklist",
    )
    time_entries_complete = models.BooleanField(default=False)
    materials_complete = models.BooleanField(default=False)
    customer_approval_confirmed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When an item was last changed; NULL until the first change.",
    )
    updated_by = models.ForeignKey(
        Staff,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Who last changed an item; NULL until the first change.",
    )

    class Meta:
        verbose_name = "Job Completion Checklist"
        verbose_name_plural = "Job Completion Checklists"

    def __str__(self) -> str:
        confirmed = sum(1 for field in self.ITEM_FIELDS if getattr(self, field))
        return f"Checklist for {self.job.name}: {confirmed}/{len(self.ITEM_FIELDS)}"
