"""The process domain's append-only audit trail: ``AuditEvent`` plus its subjects."""

from typing import ClassVar

from django.db import models

from apps.core.audit import AuditEvent


class ProcessEvent(AuditEvent):
    """One audit event on a form, entry, or procedure."""

    form = models.ForeignKey(
        "process.Form",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
    )
    form_entry = models.ForeignKey(
        "process.FormEntry",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
    )
    procedure = models.ForeignKey(
        "process.Procedure",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
    )

    EVENT_LABELS: ClassVar[dict[str, str]] = {
        "entry_created": "Entry created",
        "entry_archived": "Entry archived",
        "form_created": "Form created",
        "form_archived": "Form archived",
        "form_updated": "Form updated",
        "schema_updated": "Form schema updated",
    }

    class Meta(AuditEvent.Meta):
        pass

    def __str__(self) -> str:
        return f"{self.event_type} at {self.timestamp:%Y-%m-%d %H:%M}"
