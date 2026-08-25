"""Event writes for the process domain — the one place audit rows are made.

Services call these inside the same transaction as the row write, so an
entry change and its audit event commit or roll back together.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry, ProcessEvent


class FieldChange(TypedDict):
    """One field's before/after values, rendered into an event's description."""

    field_name: str
    old_value: str
    new_value: str


def json_safe(value: object) -> str | int | float | bool | None:
    """Convert a field value to a JSON-serializable form for delta_before/after."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def record_form_event(  # noqa: PLR0913 -- one complete event write contract
    *,
    form: Form,
    staff: Staff,
    event_type: str,
    changes: list[FieldChange],
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> ProcessEvent:
    """Write one audit event against a form definition."""
    return ProcessEvent.objects.create(
        form=form,
        staff=staff,
        event_type=event_type,
        detail={"changes": changes},
        delta_before=before,
        delta_after=after,
    )


def record_entry_event(  # noqa: PLR0913 -- one complete event write contract
    *,
    entry: FormEntry,
    staff: Staff,
    event_type: str,
    changes: list[FieldChange],
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> ProcessEvent:
    """Write one audit event against a form entry."""
    return ProcessEvent.objects.create(
        form_entry=entry,
        form=entry.form,
        staff=staff,
        event_type=event_type,
        detail={"changes": changes},
        delta_before=before,
        delta_after=after,
    )
