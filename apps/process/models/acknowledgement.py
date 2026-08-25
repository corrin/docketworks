"""Acknowledgement model — an append-only "I have read this" record.

Owner addition 2026-08-25: "I have read this" is common enough to deserve its
own model.

Fable: not a ProcessEvent — the business question an acknowledgement answers
is state (who has acknowledged this document, and when), which an event log
answers only by replaying every row against every staff member; ProcessEvent
stays the audit trail for what changed on a form/entry/procedure, not for
"has X happened yet" per staff member. Not a FormEntry either — an
acknowledgement must span procedures as well as forms (slice 2), and
FormEntry is form-only by construction (a required Form FK plus a
schema-validated data payload this model has no use for).
"""

import uuid
from typing import ClassVar

from django.db import models
from django.utils.timezone import now


class Acknowledgement(models.Model):
    """One staff member's read receipt against one form or one procedure.

    Append-only: repeat acknowledgements are allowed and create additional
    rows rather than updating an existing one — there is no update or delete
    endpoint, and no admin surface.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
        related_name="process_acknowledgements",
    )
    form = models.ForeignKey(
        "process.Form",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="acknowledgements",
    )
    procedure = models.ForeignKey(
        "process.Procedure",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="acknowledgements",
    )
    acknowledged_at = models.DateTimeField(default=now)

    class Meta:
        ordering: ClassVar = ["-acknowledged_at"]
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=(
                    models.Q(form__isnull=False, procedure__isnull=True)
                    | models.Q(form__isnull=True, procedure__isnull=False)
                ),
                name="acknowledgement_exactly_one_document",
            ),
        ]

    def __str__(self) -> str:
        document_id = self.form_id or self.procedure_id
        return f"{self.staff} acknowledged {document_id} at {self.acknowledged_at:%Y-%m-%d %H:%M}"

    @property
    def description(self) -> str:
        """Render the read-receipt sentence for the history/audit view."""
        document = self.form or self.procedure
        if document is None:  # pragma: no cover - CheckConstraint guarantees one is set
            raise ValueError("Acknowledgement has neither form nor procedure set")
        return (
            f"{self.staff.get_display_full_name()} acknowledged at "
            f"{self.acknowledged_at:%d %b %Y %H:%M} that he or she read and "
            f"understood '{document.title}'"
        )
