"""
FormEntry — filled-in instances of structured forms and registers.

Used for documents where content is structured data (inspections, logs, checklists)
rather than prose (which lives in Google Docs).
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords


class FormEntry(models.Model):
    """
    A filled-in instance of a Form definition.

    The `data` JSON field schema varies by document type. Each form type
    defines its own expected fields.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    form = models.ForeignKey(
        "Form",
        related_name="entries",
        on_delete=models.CASCADE,
        help_text="Form definition this entry belongs to",
    )

    job = models.ForeignKey(
        "job.Job",
        related_name="form_entries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Linked job (e.g. incident forms)",
    )

    entry_date = models.DateField(
        help_text="Date this entry relates to",
    )

    staff = models.ForeignKey(
        "accounts.Staff",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="form_entries",
        help_text="Staff member this entry is about (e.g. inductee, trainee)",
    )

    entered_by = models.ForeignKey(
        "accounts.Staff",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="form_entries_created",
        help_text="Staff member who created this entry",
    )

    data = models.JSONField(
        default=dict,
        help_text="Entry data - schema varies by document type",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Soft delete flag - inactive entries are hidden from normal queries",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    history: HistoricalRecords = HistoricalRecords()

    class Meta:
        ordering = ["-entry_date", "-created_at"]
        verbose_name = "Form Entry"
        verbose_name_plural = "Form Entries"

    def __str__(self):
        return f"Entry {self.entry_date} on {self.form.title}"
