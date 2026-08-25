"""Form and category endpoints for the process domain.

Paths and operationIds are the stable contract:

- GET    /api/process/categories/          process_categories_retrieve   (any staff)
- GET    /api/process/forms/               process_forms_list            (any staff)
- POST   /api/process/forms/               process_forms_create          (office staff)
- GET    /api/process/forms/{form_id}/     process_forms_retrieve        (any staff)
- PATCH  /api/process/forms/{form_id}/     process_forms_partial_update  (office staff)

There is deliberately no DELETE route on forms: archiving (PATCH
``{"status": "archived"}``) replaces delete, so a form's audit trail cannot
vanish along with the form.

Integration wiring (config/api.py): ``api.add_router("/process/", router)``.
"""

import logging
from uuid import UUID

from django.db.models import Count, Q
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth, OfficeStaffCookieJWTAuth
from apps.process.models import Form, Procedure
from apps.process.schemas import (
    CategoriesOut,
    FormCategory,
    FormCreateIn,
    FormOut,
    FormStatus,
    FormUpdateIn,
)
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
    forms = Form.objects.annotate(
        entry_count_annotated=Count("entries", filter=Q(entries__is_active=True))
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
