"""Form and category endpoints for the process domain.

Paths and operationIds are the stable contract:

- GET    /api/process/categories/                 process_categories_retrieve    (any staff)
- GET    /api/process/forms/                       process_forms_list             (any staff)
- POST   /api/process/forms/                       process_forms_create           (office staff)
- GET    /api/process/forms/{form_id}/              process_forms_retrieve         (any staff)
- PATCH  /api/process/forms/{form_id}/              process_forms_partial_update   (office staff)
- GET    /api/process/forms/{form_id}/entries/      process_forms_entries_list     (any staff)
- POST   /api/process/forms/{form_id}/entries/      process_forms_entries_create   (any staff)
- POST   /api/process/forms/{form_id}/acknowledge/  process_forms_acknowledge_create (any staff)
- GET /api/process/forms/{form_id}/acknowledgements/ process_forms_acknowledgements_list (any staff)
- GET    /api/process/entries/                     process_entries_list           (any staff)
- PATCH  /api/process/entries/{entry_id}/           process_entries_partial_update (any staff)
- DELETE /api/process/entries/{entry_id}/           process_entries_destroy        (any staff)
- GET    /api/process/entries/{entry_id}/history/   process_entries_history_list   (any staff)
- GET    /api/process/staff-options/                process_staff_options_list     (any staff)

``process_staff_options_list`` exists because ``/api/timesheets/staff/``
(the frontend's other staff-listing endpoint) is
``SuperuserCookieJWTAuth``-gated (apps/timesheet/api.py: the management
surface exposes other staff members' pay data) while any staff member must be
able to pick who a form entry is signed for — so the entry form's staff
picker needs its own any-staff endpoint rather than reusing that one.

There is deliberately no DELETE route on forms: archiving (PATCH
``{"status": "archived"}``) replaces delete, so a form's audit trail cannot
vanish along with the form. Entries get a real DELETE route, but it is soft
(``is_active=False`` plus an ``entry_archived`` event) for the same reason.

Entry reads and writes are any-staff (``CookieJWTAuth``), unlike forms'
office-staff-only writes: regular staff sign forms day to day, and the
ProcessEvent audit trail — not a permission gate — is what makes that safe.

``process_forms_acknowledge_create`` takes ``AcknowledgeIn`` (schemas.py), a
deliberately empty ``extra="forbid"`` schema — Fable: a ``staff`` field on
the wire was rejected, since acknowledging a document on someone else's
behalf is not a thing this endpoint does; ``staff`` is always
``request.user``. Declaring the empty schema (rather than no payload
parameter at all) keeps a client-supplied ``{"staff": ...}`` going through
the same RequestValidationError machinery — and the same 422 wire shape —
every other endpoint's unexpected-key rejection uses.

Integration wiring (config/api.py): ``api.add_router("/process/", router)``.
"""

import logging
from uuid import UUID

from django.db.models import Count, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.auth import CookieJWTAuth, OfficeStaffCookieJWTAuth
from apps.core.pagination import paginate
from apps.process.models import Acknowledgement, Form, FormEntry, Procedure, ProcessEvent
from apps.process.schemas import (
    AcknowledgeIn,
    AcknowledgementOut,
    CategoriesOut,
    EntryCreateIn,
    EntryEventOut,
    EntryOut,
    EntryUpdateIn,
    FormCategory,
    FormCreateIn,
    FormOut,
    FormStatus,
    FormUpdateIn,
    PaginatedEntryList,
    StaffOptionOut,
)
from apps.process.services.entries_service import (
    archive_entry,
    create_form_entry,
    update_form_entry,
)
from apps.process.services.entry_validation import display_data
from apps.process.services.forms_service import create_form, update_form

logger = logging.getLogger(__name__)

router = Router(tags=["process"])
auth = CookieJWTAuth()
office_auth = OfficeStaffCookieJWTAuth()


def _staff(request: HttpRequest) -> Staff:
    """Narrow the authenticated user to a real Staff row (ADR 0028)."""
    user = request.user
    if not isinstance(user, Staff):  # pragma: no cover - CookieJWTAuth guarantees Staff
        raise HttpError(401, "Authentication credentials were not provided.")
    return user


@router.get(
    "/categories/",
    auth=auth,
    operation_id="process_categories_retrieve",
    response=CategoriesOut,
    summary="Form and procedure category lists",
)
def process_categories_retrieve(request: HttpRequest) -> dict[str, object]:
    """Return the fixed key/label choice lists both category pickers use."""
    return {
        "forms": [{"key": key, "label": label} for key, label in Form.Category.choices],
        "procedures": [{"key": key, "label": label} for key, label in Procedure.Category.choices],
    }


@router.get(
    "/staff-options/",
    auth=auth,
    operation_id="process_staff_options_list",
    response=list[StaffOptionOut],
    summary="Staff selectable as an entry's subject, alphabetically",
)
def process_staff_options_list(request: HttpRequest) -> list[dict[str, object]]:
    """Currently-active staff, id + display name, ordered alphabetically.

    Unlike the timesheet staff list, ``actual_users=False``: signing a form
    does not require a Xero payroll id, so excluding developer/admin logins
    would only hide legitimate signers.
    """
    return [
        {"id": member.id, "name": member.get_display_full_name()}
        for member in get_displayable_staff(actual_users=False)
    ]


@router.get(
    "/forms/",
    auth=auth,
    operation_id="process_forms_list",
    response=list[FormOut],
    summary="List forms and registers",
)
def process_forms_list(
    request: HttpRequest,
    category: FormCategory | None = None,
    q: str = "",
    status: FormStatus | None = None,
) -> list[Form]:
    """List forms, newest first; archived rows are hidden unless asked for.

    ``status`` names exactly one status to show; omitted, the list excludes
    archived forms so the picker never routes staff toward a defunct form.
    """
    forms = (
        Form.objects.annotate(
            entry_count_annotated=Count("entries", filter=Q(entries__is_active=True))
        )
        # Explicit despite Meta.ordering: annotate()'s GROUP BY silently drops
        # the model's default ordering, and the list needs a stable order.
        .order_by("-created_at")
    )
    forms = forms.filter(status=status) if status is not None else forms.exclude(status="archived")
    if category is not None:
        forms = forms.filter(category=category)
    if q:
        forms = forms.filter(title__icontains=q)
    return list(forms)


@router.post(
    "/forms/",
    auth=office_auth,
    operation_id="process_forms_create",
    response={201: FormOut},
    summary="Create a form or register definition",
)
def process_forms_create(request: HttpRequest, payload: FormCreateIn) -> Status[Form]:
    """Create a form/register and its form_created audit event."""
    return Status(201, create_form(staff=_staff(request), payload=payload))


@router.get(
    "/forms/{uuid:form_id}/",
    auth=auth,
    operation_id="process_forms_retrieve",
    response=FormOut,
    summary="Retrieve one form",
)
def process_forms_retrieve(request: HttpRequest, form_id: UUID) -> Form:
    """Fetch one form definition by id."""
    return get_object_or_404(Form, pk=form_id)


@router.patch(
    "/forms/{uuid:form_id}/",
    auth=office_auth,
    operation_id="process_forms_partial_update",
    response=FormOut,
    summary="Update some fields of a form, or archive it",
)
def process_forms_partial_update(
    request: HttpRequest, form_id: UUID, payload: FormUpdateIn
) -> Form:
    """Apply only the fields the caller sent; write exactly one audit event."""
    form = get_object_or_404(Form, pk=form_id)
    return update_form(staff=_staff(request), form=form, payload=payload)


def _enrich(entries: list[FormEntry]) -> list[FormEntry]:
    """Attach display_data to every row.

    See EntryOut's docstring for why this is a required step rather than a
    resolve_* fallback.
    """
    for entry in entries:
        entry.display_data = display_data(entry.form, entry.data)
    return entries


def _entries_page(
    queryset: QuerySet[FormEntry], *, page: int, page_size: int | None
) -> dict[str, object]:
    """Paginate an entries queryset into the five-key envelope, rows enriched."""
    page_data = paginate(queryset, page=page, page_size=page_size)
    return {
        "results": _enrich(page_data.rows),
        "count": page_data.count,
        "page": page_data.page,
        "page_size": page_data.page_size,
        "total_pages": page_data.total_pages,
    }


@router.get(
    "/forms/{uuid:form_id}/entries/",
    auth=auth,
    operation_id="process_forms_entries_list",
    response=PaginatedEntryList,
    summary="List one form's entries",
)
def process_forms_entries_list(
    request: HttpRequest, form_id: UUID, page: int = 1, page_size: int | None = None
) -> dict[str, object]:
    """List one form's active entries, newest first (model Meta ordering)."""
    form = get_object_or_404(Form, pk=form_id)
    entries = (
        FormEntry.objects.filter(form=form, is_active=True)
        .select_related("form", "staff", "entered_by")
        .annotate(
            child_count_annotated=Count("child_entries", filter=Q(child_entries__is_active=True))
        )
        # Explicit despite Meta.ordering: annotate()'s GROUP BY silently drops
        # the model's default ordering, and pagination needs a stable order.
        .order_by("-entry_date", "-created_at")
    )
    return _entries_page(entries, page=page, page_size=page_size)


@router.post(
    "/forms/{uuid:form_id}/entries/",
    auth=auth,
    operation_id="process_forms_entries_create",
    response={201: EntryOut},
    summary="Create a form entry",
)
def process_forms_entries_create(
    request: HttpRequest, form_id: UUID, payload: EntryCreateIn
) -> Status[FormEntry]:
    """Create an entry against one form; stamps entered_by and writes entry_created."""
    form = get_object_or_404(Form, pk=form_id)
    entry = create_form_entry(staff=_staff(request), form=form, payload=payload)
    entry.display_data = display_data(entry.form, entry.data)
    return Status(201, entry)


@router.post(
    "/forms/{uuid:form_id}/acknowledge/",
    auth=auth,
    operation_id="process_forms_acknowledge_create",
    response={201: AcknowledgementOut},
    summary="Acknowledge that the caller read and understood a form",
)
def process_forms_acknowledge_create(
    request: HttpRequest, form_id: UUID, payload: AcknowledgeIn
) -> Status[Acknowledgement]:
    """Record a read receipt for the requesting staff member; repeats allowed.

    Self-only by construction: ``AcknowledgeIn`` has no ``staff`` field to
    accept on the wire, so the row always names ``request.user``.
    """
    form = get_object_or_404(Form, pk=form_id)
    row = Acknowledgement.objects.create(staff=_staff(request), form=form)
    return Status(201, row)


@router.get(
    "/forms/{uuid:form_id}/acknowledgements/",
    auth=auth,
    operation_id="process_forms_acknowledgements_list",
    response=list[AcknowledgementOut],
    summary="List one form's acknowledgements, newest first",
)
def process_forms_acknowledgements_list(
    request: HttpRequest, form_id: UUID
) -> list[Acknowledgement]:
    """List every acknowledgement recorded against one form (Meta ordering)."""
    form = get_object_or_404(Form, pk=form_id)
    # "form", "procedure": description's self.form.title / self.procedure.title
    # access would otherwise re-fetch the linked document once per row.
    return list(
        Acknowledgement.objects.filter(form=form).select_related("staff", "form", "procedure")
    )


@router.get(
    "/entries/",
    auth=auth,
    operation_id="process_entries_list",
    response=PaginatedEntryList,
    summary="List entries across forms",
)
def process_entries_list(  # noqa: PLR0913, PLR0917 -- One argument per public list filter.
    request: HttpRequest,
    parent: UUID | None = None,
    staff: UUID | None = None,
    job: UUID | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, object]:
    """Flat, cross-form entry list — how a meeting entry lists its actions."""
    entries = FormEntry.objects.filter(is_active=True).select_related("form", "staff", "entered_by")
    entries = entries.annotate(
        child_count_annotated=Count("child_entries", filter=Q(child_entries__is_active=True))
    )
    if parent is not None:
        entries = entries.filter(parent_entry_id=parent)
    if staff is not None:
        entries = entries.filter(staff_id=staff)
    if job is not None:
        entries = entries.filter(job_id=job)
    # Explicit despite Meta.ordering: annotate()'s GROUP BY silently drops the
    # model's default ordering, and pagination needs a stable order.
    entries = entries.order_by("-entry_date", "-created_at")
    return _entries_page(entries, page=page, page_size=page_size)


@router.patch(
    "/entries/{uuid:entry_id}/",
    auth=auth,
    operation_id="process_entries_partial_update",
    response=EntryOut,
    summary="Update some fields of a form entry",
)
def process_entries_partial_update(
    request: HttpRequest, entry_id: UUID, payload: EntryUpdateIn
) -> FormEntry:
    """Apply only the fields the caller sent; write at most one audit event."""
    entry = get_object_or_404(FormEntry, pk=entry_id)
    entry = update_form_entry(staff=_staff(request), entry=entry, payload=payload)
    entry.display_data = display_data(entry.form, entry.data)
    return entry


@router.delete(
    "/entries/{uuid:entry_id}/",
    auth=auth,
    operation_id="process_entries_destroy",
    response={204: None},
    summary="Archive a form entry (soft delete)",
)
def process_entries_destroy(request: HttpRequest, entry_id: UUID) -> Status[None]:
    """Soft-delete: set is_active=False and write entry_archived.

    The row and its audit trail both survive — nothing is hard-deleted.
    """
    entry = get_object_or_404(FormEntry, pk=entry_id)
    archive_entry(staff=_staff(request), entry=entry)
    return Status(204, None)


@router.get(
    "/entries/{uuid:entry_id}/history/",
    auth=auth,
    operation_id="process_entries_history_list",
    response=list[EntryEventOut],
    summary="An entry's audit history, newest first",
)
def process_entries_history_list(request: HttpRequest, entry_id: UUID) -> list[ProcessEvent]:
    """List every ProcessEvent recorded against one entry.

    Newest first (ProcessEvent.Meta ordering).
    """
    entry = get_object_or_404(FormEntry, pk=entry_id)
    return list(ProcessEvent.objects.filter(form_entry=entry).select_related("staff"))
