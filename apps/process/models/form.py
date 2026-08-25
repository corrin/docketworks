"""Form model — definition/template for structured entry documents (forms, registers).

Forms are append-only logs. Registers allow editing entries.
Both use FormEntry for structured data rows.
"""

import uuid
from typing import ClassVar

from django.db import models


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

    class Category(models.TextChoices):
        """One home per document; a form lists in exactly one category."""

        SAFETY = "safety", "Safety"
        TRAINING = "training", "Training"
        INCIDENT = "incident", "Incident"
        MEETING = "meeting", "Meeting"
        REGISTER = "register", "Register"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        help_text="Document type: form or register",
    )

    # Fable: null=True at the database because the v1 data restore is data-only
    # into this schema (the dump has no category column); the backfill
    # migration reruns after the restore and the API requires the field, so
    # NULL never survives past provisioning.
    category = models.CharField(  # noqa: DJ001 -- provisioning-only NULL, see comment above
        max_length=20, choices=Category.choices, null=True
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
