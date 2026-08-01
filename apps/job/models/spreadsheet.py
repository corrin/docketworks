"""The QuoteSpreadsheet model linking a Google Sheets document to a job."""

import uuid
from typing import ClassVar

from django.db import models


class QuoteSpreadsheet(models.Model):
    """Model to represent a spreadsheet for job quotes.

    This model is used to link a Google Sheets document to a job.
    """

    # CHECKLIST - when adding a new field or property to QuoteSpreadsheet, check these locations:
    #   1. QUOTESPREADSHEET_API_FIELDS or QUOTESPREADSHEET_INTERNAL_FIELDS below
    #      (if it's a model field)
    #   2. QuoteSpreadsheetSerializer in apps/job/serializers/quote_spreadsheet_serializer.py
    #   3. quote_sync_service.py in apps/job/services/ (creates/updates spreadsheets)
    #
    # Database fields exposed via API serializers
    QUOTESPREADSHEET_API_FIELDS: ClassVar[list[str]] = [
        "id",
        "sheet_id",
        "sheet_url",
        "tab",
    ]

    # Computed properties exposed via API serializers
    QUOTESPREADSHEET_API_PROPERTIES: ClassVar[list[str]] = [
        "job_id",
        "job_number",
        "job_name",
    ]

    # Internal fields not exposed in API
    QUOTESPREADSHEET_INTERNAL_FIELDS: ClassVar[list[str]] = [
        "job",
    ]

    # All QuoteSpreadsheet model fields (derived)
    QUOTESPREADSHEET_ALL_FIELDS: ClassVar[list[str]] = (
        QUOTESPREADSHEET_API_FIELDS + QUOTESPREADSHEET_INTERNAL_FIELDS
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sheet_id = models.CharField(max_length=100, help_text="Google Drive file ID")
    sheet_url = models.URLField(max_length=500, blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    tab = models.CharField(  # noqa: DJ001 -- v1 schema parity
        max_length=100, blank=True, null=True, default="Primary Details"
    )
    job = models.OneToOneField(
        "Job",
        on_delete=models.PROTECT,
        related_name="quote_sheet",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = "Quote Spreadsheet"
        verbose_name_plural = "Quote Spreadsheets"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=~models.Q(sheet_url=""), name="sheet_url_not_blank"),
            models.CheckConstraint(condition=~models.Q(tab=""), name="tab_not_blank"),
        ]

    def __str__(self) -> str:
        job = self.job
        if job is None:
            # Mirrors the AttributeError v1 raised on `None.job_number`.
            raise AttributeError("QuoteSpreadsheet has no linked job")
        return (
            f"Quote Spreadsheet for Job {job.job_number}\n"
            f"ID: {self.sheet_id}\n"
            f"URL: {self.sheet_url}\n"
            f"{'-' * 40}"
        )
