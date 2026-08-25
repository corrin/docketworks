"""Procedure model — Google Doc-backed written documents people read.

Covers SOPs, SWPs, JSAs, and reference documents.
"""

import uuid
from typing import ClassVar

from django.db import models


class Procedure(models.Model):
    """A written process document backed by Google Docs.

    Examples: SOPs, SWPs, JSAs, reference documents.
    Content lives in Google Docs — this model stores metadata and the Doc reference.
    """

    DOCUMENT_TYPES: ClassVar = [
        ("procedure", "Procedure"),
        ("reference", "Reference"),
    ]

    STATUS_CHOICES: ClassVar = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ]

    class Category(models.TextChoices):
        """One home per document; a procedure lists in exactly one category."""

        SAFETY = "safety", "Safety"
        JSA = "jsa", "JSA"
        TRAINING = "training", "Training"
        REFERENCE = "reference", "Reference"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        help_text="Document type: procedure or reference",
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
        help_text="Document number (e.g. '307' for section 3, doc 7)",
    )
    site_location = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=500,
        blank=True,
        null=True,
        help_text="Work site location",
    )

    tags = models.JSONField(
        default=list,
        blank=True,
        help_text='Free-text tags, e.g. ["safety", "machinery", "sop"]',
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
    )

    job = models.ForeignKey(
        "job.Job",
        related_name="procedures",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Linked job (required for JSA, null for SWP/SOP)",
    )

    google_doc_id = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=100,
        blank=True,
        null=True,
        help_text="Google Docs document ID",
    )
    google_doc_url = models.URLField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        blank=True,
        null=True,
        help_text="URL to edit the document in Google Docs",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar = ["-created_at"]
        verbose_name = "Procedure"
        verbose_name_plural = "Procedures"
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(document_number=""),
                name="process_procedure_document_number_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(google_doc_id=""), name="google_doc_id_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(google_doc_url=""), name="google_doc_url_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(site_location=""), name="site_location_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_document_type_display()}: {self.title}"

    @property
    def has_google_doc(self) -> bool:
        """Return whether this procedure has a linked Google Doc."""
        return bool(self.google_doc_id)
