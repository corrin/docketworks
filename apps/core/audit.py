"""The one append-only audit event shape, subclassed by every domain trail.

``JobEvent``, ``ProcessEvent``, ``PurchaseOrderEvent`` and ``TimesheetEvent``
each add their subject foreign keys to this abstract base. The base owns what
every trail populates — actor, timestamp, ``event_type``, the before/after
deltas, ``detail`` — and the rendering that turns a stored event into the
sentence a history panel shows.

Fable: an abstract base rather than multi-table inheritance. A concrete parent
table would put a join on every job-history read and need a data migration of
80,673 ``JobEvent`` rows (``docs/prod-data-shape.yml``) to serve a cross-domain
query nothing asks for. The envelope columns ``JobEvent`` carries on top
(``change_id``, ``delta_checksum``, ``dedup_hash``, ``schema_version``) stay
on ``JobEvent``: no other writer fills them, and a nullable column no writer
fills is the fake null ADR 0028 forbids.
"""

import uuid
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar, NotRequired, TypedDict

from django.db import models
from django.utils.timezone import now

#: What a JSON column holds at a leaf.
JsonScalar = str | int | float | bool | None


class FieldChange(TypedDict):
    """One field's before/after values, rendered into an event's description.

    The values are not required because job events written before 2026-04-22
    recorded only the field name; every writer since records both.
    """

    field_name: str
    old_value: NotRequired[JsonScalar]
    new_value: NotRequired[JsonScalar]


class AuditDetail(TypedDict, total=False):
    """What every trail may store in ``detail``; a subtype extends it with its own keys."""

    changes: list[FieldChange]
    note_text: str


def json_safe(value: object) -> JsonScalar:
    """Convert a field value to a JSON-serializable form for delta_before/after.

    ``value`` is ``object`` because it arrives from JSON columns and model
    fields alike; the isinstance chain is the boundary validation.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def snapshot_changes(
    before: Mapping[str, object] | None, after: Mapping[str, object] | None
) -> list[FieldChange]:
    """Diff two snapshots key-wise into the changes a description renders.

    A key present in only one side is a change from or to ``""``; a key whose
    value is equal on both sides is not reported, so a write that touched one
    field reads as one sentence.
    """
    before = before or {}
    after = after or {}
    keys = list(before) + [key for key in after if key not in before]
    changes: list[FieldChange] = []
    for key in keys:
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        changes.append(
            {
                "field_name": key,
                "old_value": "" if old is None else str(json_safe(old)),
                "new_value": "" if new is None else str(json_safe(new)),
            }
        )
    return changes


def truncate(text: JsonScalar, max_chars: int = 60) -> str:
    """Shorten a value for a one-line description."""
    if text is None or text == "":
        return ""
    text_str = str(text)
    if len(text_str) <= max_chars:
        return text_str
    return text_str[: max_chars - 1].rstrip() + "…"


def truncate_change(label: str, old: JsonScalar, new: JsonScalar) -> str:
    """Describe a change to a long text field without quoting all of it."""
    return f"{label} changed from '{truncate(old)}' to '{truncate(new)}'"


def default_descriptor(field_name: str, old: JsonScalar, new: JsonScalar) -> str:
    """Render a field change with no registered descriptor."""
    return f"{field_name} changed from '{old}' to '{new}'"


class AuditEvent(models.Model):
    """One append-only audit event; every domain trail subclasses this.

    A subtype shapes how its events read through two class tables, and may
    override ``build_description`` for event kinds whose detail is its own
    (JobEvent's invoices, quotes and priority moves):

    - ``FIELD_DESCRIPTORS``: field name → ``(old, new)`` → sentence, for the
      fields in ``detail.changes`` that read badly as "X changed from A to B".
    - ``EVENT_LABELS``: ``event_type`` → fixed sentence, for events that carry
      no changes (a creation, an archive).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=now)
    staff = models.ForeignKey("accounts.Staff", on_delete=models.PROTECT)
    event_type = models.CharField(max_length=100)
    delta_before = models.JSONField(null=True, blank=True)
    delta_after = models.JSONField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    FIELD_DESCRIPTORS: ClassVar[dict[str, Callable[[JsonScalar, JsonScalar], str]]] = {}
    EVENT_LABELS: ClassVar[dict[str, str]] = {}

    class Meta:
        abstract = True
        ordering: ClassVar[list[str]] = ["-timestamp"]

    @classmethod
    def render_change(cls, change: FieldChange) -> str:
        """Render one ``detail.changes`` entry through the subtype's descriptors."""
        field = change["field_name"]
        # Fallback for events written before 2026-04-22, the last date a job event
        # was recorded without structured values. Those rows name the field that
        # moved but not what it moved between, because the writer of the day stored
        # only a rendered sentence. The values cannot be recovered — nothing else
        # holds a job's notes or description as they were at that moment — so this
        # says what is known. Rendering "changed from '' to ''" was rejected: it
        # asserts a change to empty, which is a different and false fact. Every
        # writer since records both values, so no new row reaches this branch.
        # The text says so outright. "Notes updated" reads like an ordinary entry
        # and hides that the before and after are gone; someone auditing the job
        # would take it at face value and stop looking.
        if "old_value" not in change and "new_value" not in change:
            return f"{field} changed (details lost)" if field else "Changed (details lost)"
        old = change.get("old_value", "")
        new = change.get("new_value", "")
        descriptor = cls.FIELD_DESCRIPTORS.get(field)
        if descriptor:
            return descriptor(old, new)
        return default_descriptor(field, old, new)

    @classmethod
    def build_changes_description(cls, detail: AuditDetail) -> str:
        """Join every rendered change into one sentence; empty when there are none."""
        changes = detail.get("changes", [])
        if not changes:
            return ""
        parts = [cls.render_change(change) for change in changes]
        return ". ".join(part for part in parts if part)

    @staticmethod
    def manual_note_description(detail: AuditDetail) -> str:
        """Render a typed note as its own text; empty when the detail holds none."""
        return detail.get("note_text", "")

    def build_description(self) -> str:
        """Generate the human-readable sentence from ``event_type`` and ``detail``.

        The recorded changes render first; then a typed note; then the
        subtype's fixed label; then a ``f"({event_type})"`` sentinel that a
        label or a subtype's override makes unreachable.
        """
        detail: AuditDetail = self.detail
        rendered = self.build_changes_description(detail)
        if rendered:
            return rendered
        note = self.manual_note_description(detail)
        if note:
            return note
        label = self.EVENT_LABELS.get(self.event_type)
        if label:
            return label
        return f"({self.event_type})"

    @property
    def description(self) -> str:
        """Human-readable description of the event."""
        return self.build_description()
