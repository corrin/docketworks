"""
Procedure model — Google Doc-backed written documents people read.

Covers SOPs, SWPs, JSAs, and reference documents.
"""

import uuid

from django.db import models
from simple_history.models import HistoricalRecords


class Procedure(models.Model):
    """
    A written process document backed by Google Docs.

    Examples: SOPs, SWPs, JSAs, reference documents.
    Content lives in Google Docs — this model stores metadata and the Doc reference.
    """

    DOCUMENT_TYPES = [
        ("procedure", "Procedure"),
        ("reference", "Reference"),
    ]

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPES,
        help_text="Document type: procedure or reference",
    )

    title = models.CharField(max_length=255)
    document_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Document number (e.g. '307' for section 3, doc 7)",
    )
    site_location = models.CharField(
        max_length=500,
        blank=True,
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

    google_doc_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Google Docs document ID",
    )
    google_doc_url = models.URLField(
        blank=True,
        help_text="URL to edit the document in Google Docs",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history: HistoricalRecords = HistoricalRecords()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Procedure"
        verbose_name_plural = "Procedures"

    def __str__(self):
        return f"{self.get_document_type_display()}: {self.title}"

    @property
    def has_google_doc(self) -> bool:
        return bool(self.google_doc_id)
