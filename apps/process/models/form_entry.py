"""FormEntry — filled-in instances of structured forms and registers.

Used for documents where content is structured data (inspections, logs, checklists)
rather than prose (which lives in Google Docs).
"""

import uuid
from typing import TYPE_CHECKING, ClassVar

from django.db import models


class FormEntry(models.Model):
    """A filled-in instance of a Form definition.

    The `data` JSON field schema varies by document type. Each form type
    defines its own expected fields.
    """

    if TYPE_CHECKING:
        # Not a model field: apps/process/schemas.py's EntryOut declares
        # display_data as a plain field with no resolve_* fallback, so every
        # endpoint returning an entry must set this attribute on the instance
        # before serialisation (apps/process/api.py). TYPE_CHECKING-only so
        # mypy accepts that assignment without Django ever seeing a real
        # field to migrate.
        display_data: dict[str, str]

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

    # Fable: SET_NULL, not CASCADE — an action extracted from a meeting stands
    # on its own as a record; only test cleanup hard-deletes, and orphaning a
    # child there is harmless. NULL parent is the normal unlinked state.
    parent_entry = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_entries",
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

    # Fable: null=True at the database, matching Form.category — the v1 data
    # restore is data-only into this schema and v1's formentry table predates
    # this column, so pg_restore's COPY supplies no value for it and auto_now
    # (a Python-side default) never runs during a raw restore. The backfill
    # migration (0007) reruns after the restore and every save() sets this via
    # auto_now, so NULL never survives past provisioning.
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering: ClassVar = ["-entry_date", "-created_at"]
        verbose_name = "Form Entry"
        verbose_name_plural = "Form Entries"

    def __str__(self) -> str:
        return f"Entry {self.entry_date} on {self.form.title}"
