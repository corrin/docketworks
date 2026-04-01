"""
Form model — definition/template for structured entry documents (forms, registers).

Forms are append-only logs. Registers allow editing entries.
Both use FormEntry for structured data rows.
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords


class Form(models.Model):
    """
    A form/register definition (template).

    Defines the schema and metadata. Filled-in instances are FormEntry rows,
    not additional Form records.
    """

    DOCUMENT_TYPES = [
        ("form", "Form"),
        ("register", "Register"),
    ]

    STATUS_CHOICES = [
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
    document_number = models.CharField(
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
        ordering = ["-created_at"]
        verbose_name = "Form"
        verbose_name_plural = "Forms"

    def __str__(self):
        return f"{self.get_document_type_display()}: {self.title}"
