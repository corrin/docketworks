"""Form model — definition/template for structured entry documents (forms, registers).

Forms are append-only logs. Registers allow editing entries.
Both use FormEntry for structured data rows.
"""

import uuid
from typing import ClassVar

from django.db import models
from simple_history.models import HistoricalRecords


class Form(models.Model):
    """A form/register definition (template).

    Defines the schema and metadata. Filled-in instances are FormEntry rows,
    not additional Form records.
    """

    DOCUMENT_TYPES: ClassVar = [
        ("form", "Form"),
        ("register", "Register"),
    ]

    STATUS_CHOICES: ClassVar = [
        ("active", "Active"),
        ("archived", "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        help_text="Document type: form or register",
    )

    title = models.CharField(max_length=255)
    document_number = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=50,
        blank=True,
        null=True,
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        help_text='Free-text tags, e.g. ["safety", "inspection"]',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
    )

    form_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON schema defining entry fields for form templates",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history: HistoricalRecords = HistoricalRecords()

    class Meta:
        ordering: ClassVar = ["-created_at"]
        verbose_name = "Form"
        verbose_name_plural = "Forms"
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(document_number=""),
                name="process_form_document_number_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_document_type_display()}: {self.title}"
