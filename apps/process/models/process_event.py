"""The process domain's append-only audit trail.

Mirrors JobEvent's delta shape (staff, event_type, delta_before/after,
detail.changes, derived description) without the envelope machinery —
checksums, undo and change ids exist for the job screen's optimistic
concurrency, which this domain does not have. Hoisting a shared event
mechanism into apps/core is recorded post-cutover work (see the design doc).
"""

import uuid
from typing import Any, ClassVar

from django.db import models
from django.utils.timezone import now


def _default_descriptor(field_name: str, old: object, new: object) -> str:
    return f"{field_name} changed from '{old}' to '{new}'"


def _render_change(change: dict[str, Any]) -> str:
    return _default_descriptor(
        change.get("field_name", ""), change.get("old_value", ""), change.get("new_value", "")
    )


_EVENT_LABELS: dict[str, str] = {
    "entry_created": "Entry created",
    "entry_archived": "Entry archived",
    "form_created": "Form created",
    "form_archived": "Form archived",
    "schema_updated": "Form schema updated",
}


class ProcessEvent(models.Model):
    """One audit event on a form, entry, or procedure."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=now)
    staff = models.ForeignKey("accounts.Staff", on_delete=models.PROTECT)
    event_type = models.CharField(max_length=50)
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
    delta_before = models.JSONField(null=True, blank=True)
    delta_after = models.JSONField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering: ClassVar = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.event_type} at {self.timestamp:%Y-%m-%d %H:%M}"

    @property
    def description(self) -> str:
        """Human-readable sentence for the history panel."""
        changes = (self.detail or {}).get("changes", [])
        if changes:
            parts = [_render_change(change) for change in changes]
            rendered = ". ".join(part for part in parts if part)
            if rendered:
                return rendered
        label = _EVENT_LABELS.get(self.event_type)
        if label:
            return label
        return f"({self.event_type})"
