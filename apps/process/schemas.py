"""Wire contracts for the process domain.

The form schema is typed here so invalid structure is a 422 at the request
boundary (extra="forbid" everywhere); entry DATA is validated dynamically
against the stored schema in services/entry_validation.py, surfacing as a
transparent 400 (the codebase's convention for post-parse validation).
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, model_validator

from apps.core.schemas import NonBlankText, NullableText, omittable
from apps.process.models import Form, FormEntry, ProcessEvent

FieldType = Literal["text", "textarea", "date", "boolean", "number", "select", "staff", "entry_ref"]
FormCategory = Literal["safety", "training", "incident", "meeting", "register"]
FormDocumentType = Literal["form", "register"]
FormStatus = Literal["active", "archived"]


class FormFieldSchema(Schema):
    """One field of a form's entry schema.

    options only on select; source_form + display_key exactly on entry_ref —
    an Asset Register is just another form, and a maintenance record's asset
    field is an entry_ref into it.
    """

    model_config = ConfigDict(extra="forbid")

    key: NonBlankText
    label: NonBlankText
    type: FieldType
    required: bool = False
    options: list[NonBlankText] | None = None
    source_form: UUID | None = None
    display_key: NonBlankText | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "FormFieldSchema":
        if self.type == "select":
            if not self.options:
                raise ValueError(f"Field '{self.key}': a select field needs options.")
        elif self.options is not None:
            raise ValueError(f"Field '{self.key}': options belong only on select fields.")
        if self.type == "entry_ref":
            if self.source_form is None or self.display_key is None:
                raise ValueError(
                    f"Field '{self.key}': an entry_ref field needs source_form and display_key."
                )
        elif self.source_form is not None or self.display_key is not None:
            raise ValueError(
                f"Field '{self.key}': source_form/display_key belong only on entry_ref fields."
            )
        return self


class FormSchemaSpec(Schema):
    """A form's whole entry schema; keys must be unique."""

    model_config = ConfigDict(extra="forbid")

    fields: list[FormFieldSchema]

    @model_validator(mode="after")
    def _unique_keys(self) -> "FormSchemaSpec":
        keys = [field.key for field in self.fields]
        duplicates = {key for key in keys if keys.count(key) > 1}
        if duplicates:
            raise ValueError(f"Duplicate field keys: {sorted(duplicates)}.")
        return self


class FormCreateIn(Schema):
    """POST body. Unknown keys are a 422, not a silent drop."""

    model_config = ConfigDict(extra="forbid")

    document_type: FormDocumentType
    category: FormCategory
    title: NonBlankText
    document_number: NullableText = omittable(None)
    tags: list[NonBlankText] = omittable([])
    form_schema: FormSchemaSpec


class FormUpdateIn(Schema):
    """PATCH body; omission leaves a field alone (exclude_unset).

    Fable: defaults below are placeholders never read by handlers (they parse
    with ``model_dump(exclude_unset=True)``); ``FormSchemaSpec(fields=[])`` is
    a fresh instance per default-factory call, not a shared mutable default,
    matching the same-file convention on ``EntryUpdateIn``.
    """

    model_config = ConfigDict(extra="forbid")

    category: FormCategory = omittable("safety")
    title: NonBlankText = omittable("")
    document_number: NullableText = omittable(None)
    tags: list[NonBlankText] = omittable([])
    status: FormStatus = omittable("active")
    form_schema: FormSchemaSpec = omittable(FormSchemaSpec(fields=[]))


class FormOut(Schema):
    """One form, list row and detail alike (the edit dialog reads the row)."""

    id: UUID
    document_type: str
    category: str
    title: str
    document_number: str | None
    tags: list[str]
    status: str
    form_schema: dict[str, object]
    entry_count: int
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_entry_count(obj: Form) -> int:
        """Read the list queryset's annotation, or count for a single row."""
        annotated = getattr(obj, "entry_count_annotated", None)
        if annotated is not None:
            return int(annotated)
        return obj.entries.filter(is_active=True).count()


class EntryCreateIn(Schema):
    """POST body for creating a form/register entry."""

    model_config = ConfigDict(extra="forbid")

    entry_date: date
    data: dict[str, object]
    job: UUID | None = omittable(None)
    staff: UUID | None = omittable(None)
    parent_entry: UUID | None = omittable(None)


class EntryUpdateIn(Schema):
    """PATCH body; omission leaves a field alone (exclude_unset).

    Fable: defaults below are placeholders never read by handlers (they parse
    with ``model_dump(exclude_unset=True)``), same convention as
    ``StaffUpdateIn``.
    """

    model_config = ConfigDict(extra="forbid")

    entry_date: date = omittable(date(2000, 1, 1))
    data: dict[str, object] = omittable({})
    job: UUID | None = omittable(None)
    staff: UUID | None = omittable(None)
    parent_entry: UUID | None = omittable(None)


class EntryOut(Schema):
    """One form entry — the entry list row and the entry detail alike.

    ``display_data`` carries server-resolved labels for staff/entry_ref values
    (e.g. a staff UUID's display name, a referenced entry's display_key value)
    so the client renders a row with no follow-up join. It is a plain
    declared field, not a ``resolve_*`` staticmethod: computing it needs the
    form's schema plus, for entry_ref fields, the referenced entry, which a
    single-hop ``resolve_*(obj)`` cannot reach, so the endpoint (Task 8) must
    set ``entry.display_data`` on the ORM instance itself before
    serialisation.

    Fable: a ``resolve_*`` fallback such as ``getattr(obj, "display_data",
    {})`` was rejected — it would turn a missing enrichment pass into a
    silent empty dict instead of the loud ``AttributeError`` a plain field
    raises at serialisation time, and fail-early treats "the endpoint forgot
    to enrich this entry" as a bug to surface, not a value to default over.
    """

    id: UUID
    form: UUID
    entry_date: date
    staff: UUID | None
    staff_name: str | None
    entered_by: UUID | None
    entered_by_name: str | None
    job: UUID | None
    parent_entry: UUID | None
    child_count: int
    data: dict[str, object]
    display_data: dict[str, str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_staff_name(obj: FormEntry) -> str | None:
        """Resolve the subject staff member's display name, or None if unset."""
        return obj.staff.get_display_full_name() if obj.staff else None

    @staticmethod
    def resolve_entered_by_name(obj: FormEntry) -> str | None:
        """Resolve the recording staff member's display name, or None if unset."""
        return obj.entered_by.get_display_full_name() if obj.entered_by else None

    @staticmethod
    def resolve_child_count(obj: FormEntry) -> int:
        """Read the list queryset's annotation, or count for a single row."""
        annotated = getattr(obj, "child_count_annotated", None)
        if annotated is not None:
            return int(annotated)
        return obj.child_entries.filter(is_active=True).count()


class PaginatedEntryList(Schema):
    """Wire contract for a paginated list of form entries."""

    results: list[EntryOut]
    count: int
    page: int
    page_size: int
    total_pages: int


class CategoryOut(Schema):
    """One selectable category (key/label pair) for a document picker."""

    key: str
    label: str


class CategoriesOut(Schema):
    """The category pickers for forms/registers and procedures."""

    forms: list[CategoryOut]
    procedures: list[CategoryOut]


class EntryEventOut(Schema):
    """One audit event on a form entry, for the entry's history panel."""

    id: UUID
    timestamp: datetime
    event_type: str
    staff_name: str
    description: str
    changes: list[dict[str, str]]

    @staticmethod
    def resolve_staff_name(obj: ProcessEvent) -> str:
        """Resolve the acting staff member's display name."""
        return obj.staff.get_display_full_name()

    @staticmethod
    def resolve_changes(obj: ProcessEvent) -> list[dict[str, str]]:
        """Read the event's recorded field changes, empty if it made none."""
        # detail defaults to {} at the model; absent "changes" means an event
        # with no field changes (e.g. entry_created), not corrupt data. The
        # per-field str() casts (not a dict.get fallback) are what keep this
        # list[dict[str, str]] rather than JSONField's Any at the type level.
        raw_changes = obj.detail.get("changes", [])
        return [
            {
                "field_name": str(change["field_name"]),
                "old_value": str(change["old_value"]),
                "new_value": str(change["new_value"]),
            }
            for change in raw_changes
        ]
