"""Form definition writes: row + one ProcessEvent, one transaction.

Task 8's entry writes need the identical shape (row write and audit event
commit or roll back together); this module is the template to extend, not a
one-off — see apps.process.services.process_events for the event contract.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from ninja.errors import HttpError

from apps.accounts.models import Staff
from apps.process.models import Form
from apps.process.schemas import FormCreateIn, FormSchemaSpec, FormUpdateIn
from apps.process.services.process_events import FieldChange, json_safe, record_form_event

logger = logging.getLogger(__name__)


def create_form(*, staff: Staff, payload: FormCreateIn) -> Form:
    """Create a form/register definition and its form_created event."""
    _require_source_forms_exist(payload.form_schema)
    with transaction.atomic():
        form = Form.objects.create(
            document_type=payload.document_type,
            category=payload.category,
            title=payload.title,
            document_number=payload.document_number,
            tags=list(payload.tags),
            form_schema=payload.form_schema.model_dump(mode="json", exclude_none=True),
            status="active",
        )
        record_form_event(form=form, staff=staff, event_type="form_created", changes=[])
    return form


def update_form(*, staff: Staff, form: Form, payload: FormUpdateIn) -> Form:
    """Apply only the fields the caller actually changed; at most one event.

    Mirrors ``accounts_staff_partial_update`` for presence (``exclude_unset``
    against the schema's placeholder defaults), then goes one step further:
    presence is not "changed" — a supplied field whose value equals the
    stored one (a redundant re-archive included) is dropped before the event
    is built. A PATCH that changes nothing writes no event at all — the
    fail-early-honest reading of "nothing happened" over "diff against
    nothing". ``form_archived`` fires only on an actual active -> archived
    transition, never on repeating an already-archived status.
    """
    supplied = payload.model_dump(exclude_unset=True)
    if "form_schema" in supplied:
        _require_source_forms_exist(payload.form_schema)
        # UUID-bearing entry_ref fields need JSON mode: the plain python-mode
        # dump above still holds UUID objects, and Form.form_schema has no
        # custom encoder to stringify them.
        supplied["form_schema"] = payload.form_schema.model_dump(mode="json", exclude_none=True)

    prior_status = form.status
    changed_fields: set[str] = set()
    changes: list[FieldChange] = []
    for field, value in supplied.items():
        old = getattr(form, field)
        if old == value:
            continue
        changed_fields.add(field)
        changes.append(
            {
                "field_name": field.replace("_", " ").title(),
                "old_value": str(json_safe(old)),
                "new_value": str(json_safe(value)),
            }
        )
        setattr(form, field, value)

    try:
        form.full_clean()
    except DjangoValidationError as exc:
        # Converted rather than left to escape: an unhandled ValidationError is
        # a 500, and a rejected form value is the caller's to fix. Same
        # flattening as accounts_staff_partial_update.
        raise HttpError(400, "; ".join(exc.messages)) from exc

    with transaction.atomic():
        form.save()
        if changes:
            archived_now = "status" in changed_fields and form.status == "archived"
            if archived_now and prior_status != "archived":
                event_type = "form_archived"
            elif "form_schema" in changed_fields:
                event_type = "schema_updated"
            else:
                event_type = "form_updated"
            record_form_event(form=form, staff=staff, event_type=event_type, changes=changes)
    return form


def _require_source_forms_exist(schema: FormSchemaSpec) -> None:
    """Reject entry_ref fields whose source_form UUID matches no Form."""
    wanted = {f.source_form for f in schema.fields if f.source_form is not None}
    found = set(Form.objects.filter(pk__in=wanted).values_list("pk", flat=True))
    missing = wanted - found
    if missing:
        raise HttpError(400, f"entry_ref source form(s) not found: {sorted(map(str, missing))}.")
