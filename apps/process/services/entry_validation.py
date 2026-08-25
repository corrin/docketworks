"""Entry data validated against its form's stored schema, at write time.

Raises transparent 400s (the post-parse validation convention); the schema
STRUCTURE was already a 422 at form-write time via FormSchemaSpec.
"""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from ninja.errors import HttpError

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry
from apps.process.schemas import FormFieldSchema, FormSchemaSpec


def parse_schema(form: Form) -> FormSchemaSpec:
    """Re-validate the stored schema.

    Loud on corruption: every write path validates, so an unparseable stored
    schema is data damage, not input.
    """
    try:
        return FormSchemaSpec.model_validate(form.form_schema)
    except ValueError as exc:
        raise HttpError(500, f"Stored schema for form '{form.title}' is invalid: {exc}") from exc


def _as_uuid(key: str, value: object, problems: list[str]) -> UUID | None:
    if not isinstance(value, str):
        problems.append(f"'{key}' must be an id string.")
        return None
    try:
        return UUID(value)
    except ValueError:
        problems.append(f"'{key}' must be an id string.")
        return None


def _check_text(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    if not isinstance(value, str):
        problems.append(f"'{field.key}' must be text.")


def _check_number(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"'{field.key}' must be a number.")


def _check_boolean(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    if not isinstance(value, bool):
        problems.append(f"'{field.key}' must be true or false.")


def _check_date(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    if not isinstance(value, str):
        problems.append(f"'{field.key}' must be an ISO date string.")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        problems.append(f"'{field.key}' must be an ISO date (YYYY-MM-DD).")


def _check_select(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    if value not in (field.options or []):
        problems.append(f"'{field.key}' must be one of {field.options}.")


def _check_staff(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    staff_id = _as_uuid(field.key, value, problems)
    if staff_id is not None and not Staff.objects.filter(pk=staff_id).exists():
        problems.append(f"'{field.key}' does not name a known staff member.")


def _check_entry_ref(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    entry_id = _as_uuid(field.key, value, problems)
    if field.source_form is None:  # pragma: no cover - FormFieldSchema._coherent forbids this
        # Fable: FormFieldSchema._coherent guarantees source_form is set
        # whenever type == "entry_ref"; this branch documents that invariant
        # for mypy rather than adding a new runtime check.
        raise AssertionError(f"entry_ref field '{field.key}' has no source_form")
    if (
        entry_id is not None
        and not FormEntry.objects.filter(
            pk=entry_id, form_id=field.source_form, is_active=True
        ).exists()
    ):
        problems.append(f"'{field.key}' does not name an active entry of its source form.")


_CHECKERS: dict[str, Callable[[FormFieldSchema, object, list[str]], None]] = {
    "text": _check_text,
    "textarea": _check_text,
    "number": _check_number,
    "boolean": _check_boolean,
    "date": _check_date,
    "select": _check_select,
    "staff": _check_staff,
    "entry_ref": _check_entry_ref,
}


def _check_value(field: FormFieldSchema, value: object, problems: list[str]) -> None:
    checker = _CHECKERS.get(field.type)
    if checker is None:  # pragma: no cover - FieldType is a closed Literal
        raise AssertionError(f"Unhandled field type {field.type}")
    checker(field, value, problems)


def validate_entry_data(form: Form, data: dict[str, object]) -> None:
    """Report every violation at once - a fixable 400, not a guessing game."""
    spec = parse_schema(form)
    by_key = {field.key: field for field in spec.fields}
    problems: list[str] = []

    for key in data:
        if key not in by_key:
            problems.append(f"'{key}' is not a field of this form.")
    for field in spec.fields:
        if field.required and (field.key not in data or data[field.key] in ("", None)):
            problems.append(f"'{field.key}' is required.")
            continue
        if field.key in data and data[field.key] is not None:
            _check_value(field, data[field.key], problems)

    if problems:
        raise HttpError(400, "; ".join(problems))


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def display_data(form: Form, data: dict[str, object]) -> dict[str, str]:
    """Resolve staff/entry_ref values to human labels.

    Resolved server-side so tables never show a UUID. A missing referent
    renders as the raw id - reads must not 500 on rows removed outside the
    app.
    """
    spec = parse_schema(form)
    resolved: dict[str, str] = {}
    for field in spec.fields:
        value = data.get(field.key)
        if not isinstance(value, str) or value == "":
            continue
        if field.type == "staff":
            staff = Staff.objects.filter(pk=value).first() if _is_uuid(value) else None
            resolved[field.key] = staff.get_display_full_name() if staff else value
        elif field.type == "entry_ref":
            source = FormEntry.objects.filter(pk=value).first() if _is_uuid(value) else None
            if source is None:
                resolved[field.key] = value
            else:
                label = source.data.get(field.display_key or "")
                resolved[field.key] = str(label) if label not in (None, "") else value
    return resolved
