"""Procedure model — Google Doc-backed written documents people read.

Covers SOPs, SWPs, JSAs, and reference documents.
"""

import uuid
from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy


class Procedure(models.Model):
    """A written process document backed by Google Docs.

    Examples: SOPs, SWPs, JSAs, reference documents.
    Content lives in Google Docs — this model stores metadata and the Doc reference.
    """

    DOCUMENT_TYPES: ClassVar = [
        ("procedure", gettext_lazy("Procedure")),
        ("reference", gettext_lazy("Reference")),
    ]

    STATUS_CHOICES: ClassVar = [
        ("draft", gettext_lazy("Draft")),
        ("active", gettext_lazy("Active")),
        ("completed", gettext_lazy("Completed")),
        ("archived", gettext_lazy("Archived")),
    ]

    class Category(models.TextChoices):
        """One home per document; a procedure lists in exactly one category."""

        SAFETY = "safety", gettext_lazy("Safety")
        JSA = "jsa", gettext_lazy("JSA")
        TRAINING = "training", gettext_lazy("Training")
        REFERENCE = "reference", gettext_lazy("Reference")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        help_text=gettext_lazy("Document type: procedure or reference"),
    )

    category = models.CharField(max_length=20, choices=Category.choices)

    title = models.CharField(max_length=255)
    document_number = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=50,
        blank=True,
        null=True,
        help_text=gettext_lazy("Document number (e.g. '307' for section 3, doc 7)"),
    )
    site_location = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=500,
        blank=True,
        null=True,
        help_text=gettext_lazy("Work site location"),
    )

    tags = models.JSONField(
        default=list,
        blank=True,
        help_text=gettext_lazy('Free-text tags, e.g. ["safety", "machinery", "sop"]'),
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
        help_text=gettext_lazy("Linked job (required for JSA, null for SWP/SOP)"),
    )

    google_doc_id = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=100,
        blank=True,
        null=True,
        help_text=gettext_lazy("Google Docs document ID"),
    )
    google_doc_url = models.URLField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        blank=True,
        null=True,
        help_text=gettext_lazy("URL to edit the document in Google Docs"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar = ["-created_at"]
        verbose_name = gettext_lazy("Procedure")
        verbose_name_plural = gettext_lazy("Procedures")
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
