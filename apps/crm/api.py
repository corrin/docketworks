"""CRM phone-call API.

Paths and operationIds are the stable contract; the frontend generates its
client from ``frontend/schema.v2.yml``.
Mounted at ``/api/crm/`` by
config/api.py: ``api.add_router("/crm/", router)``.

- GET    /api/crm/phone-calls/                      crm_phone_calls_list
- GET    /api/crm/phone-calls/{id}/                 crm_phone_calls_retrieve
- POST   /api/crm/phone-calls/{id}/assign-number/   assignPhoneCallNumber
- POST   /api/crm/phone-calls/{id}/job-link/        linkPhoneCallJob
- DELETE /api/crm/phone-calls/{id}/job-link/        unlinkPhoneCallJob
- GET    /api/crm/phone-call-recordings/            crm_phone_call_recordings_list
- GET    /api/crm/phone-call-recordings/{id}/       crm_phone_call_recordings_retrieve
- GET    /api/crm/phone-call-recordings/{id}/download/       downloadPhoneCallRecording
- DELETE /api/crm/phone-call-recordings/{id}/local-file/     deleteLocalPhoneCallRecording
- DELETE /api/crm/phone-call-recordings/{id}/provider-file/  deleteProviderPhoneCallRecording
- GET    /api/crm/phone-endpoints/                  crm_phone_endpoints_list
- POST   /api/crm/phone-endpoints/                  crm_phone_endpoints_create
- GET    /api/crm/phone-endpoints/{id}/             crm_phone_endpoints_retrieve
- PUT    /api/crm/phone-endpoints/{id}/             crm_phone_endpoints_update
- PATCH  /api/crm/phone-endpoints/{id}/             crm_phone_endpoints_partial_update
- DELETE /api/crm/phone-endpoints/{id}/             crm_phone_endpoints_destroy

Authorization requires office staff for calls and recording reads; superuser
for recording deletes and endpoint admin. The provider connection settings are
``/api/integration-settings/`` in apps/core. The phone-provider *ingestion*
URLs are not here — ingestion is a poll of the provider portal (see
services/phone_call_service.py, EXACT-URL PIN).
"""

import mimetypes
from collections.abc import Callable, Sequence
from datetime import date
from typing import TYPE_CHECKING, TypedDict, cast
from uuid import UUID

from django.db.models import (
    Case,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponseBase,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.utils.cache import get_conditional_response
from ninja import Query, Router
from ninja.errors import AuthorizationError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.company.models import ContactMethod
from apps.core.auth import CookieJWTAuth
from apps.core.errors import persist_app_error
from apps.core.pagination import paginate
from apps.crm.models import PhoneCallRecord, PhoneCallRecording, PhoneEndpoint
from apps.crm.schemas import (
    OperationErrorOut,
    PaginatedPhoneCallRecordsOut,
    PhoneCallJobLinkIn,
    PhoneCallListFilters,
    PhoneCallRecordingOut,
    PhoneCallRecordOut,
    PhoneEndpointCreateIn,
    PhoneEndpointOut,
    PhoneEndpointPatchIn,
    PhoneEndpointPutIn,
    PhoneNumberAssignmentIn,
)
from apps.crm.services.phone_call_service import (
    assign_phone_number_from_call,
    delete_local_recording,
    link_phone_call_to_job,
    normalize_phone,
    provider_delete_recording,
    recording_file_path,
    unlink_phone_call_job,
)
from apps.crm.tasks import rematch_phone_calls_task

if TYPE_CHECKING:
    # Evaluated only by the type checker (annotation is quoted at use site), so
    # the dev-only django_stubs_ext dependency is never imported at runtime.
    from django_stubs_ext import WithAnnotations

router = Router(tags=["CRM"], auth=CookieJWTAuth())

FieldErrors = dict[str, list[str]]


def _require_office_staff(request: HttpRequest) -> Staff:
    """Require the authenticated user to have ``is_office_staff``."""
    user = request.user
    if not isinstance(user, Staff) or not user.is_office_staff:
        raise AuthorizationError
    return user


def _require_superuser(request: HttpRequest) -> Staff:
    """Require the authenticated user to be a superuser."""
    user = request.user
    if not isinstance(user, Staff) or not user.is_superuser:
        raise AuthorizationError
    return user


# ---------------------------------------------------------------------------
# Phone calls
# ---------------------------------------------------------------------------


def _base_call_queryset() -> QuerySet[PhoneCallRecord]:
    return (
        PhoneCallRecord.objects.select_related(
            "company",
            "person",
            "job",
            "job_linked_by",
            "origin_endpoint",
            "destination_endpoint",
        )
        .filter(Q(origin__gt="") | Q(destination__gt=""))
        .order_by("-call_datetime")
    )


def _apply_uuid_filters(
    queryset: QuerySet[PhoneCallRecord],
    filters: PhoneCallListFilters,
) -> QuerySet[PhoneCallRecord]:
    uuid_filters = {
        "company_id": filters.company,
        "person_id": filters.person,
        "job_id": filters.job,
        "origin_endpoint_id": filters.origin_endpoint,
        "destination_endpoint_id": filters.destination_endpoint,
    }
    return queryset.filter(**{name: value for name, value in uuid_filters.items() if value})


def _apply_match_filters(
    queryset: QuerySet[PhoneCallRecord],
    filters: PhoneCallListFilters,
) -> QuerySet[PhoneCallRecord]:
    if filters.company_match == "matched":
        queryset = queryset.filter(company_id__isnull=False)
    elif filters.company_match == "unmatched":
        queryset = queryset.filter(company_id__isnull=True)
    if filters.job_link == "linked":
        queryset = queryset.filter(job_id__isnull=False)
    elif filters.job_link == "unlinked":
        queryset = queryset.filter(job_id__isnull=True)
    if filters.direction != "all":
        queryset = queryset.filter(direction=filters.direction)
    if filters.has_recording is not None:
        queryset = queryset.filter(recording__isnull=not filters.has_recording)
    return queryset


def _apply_date_filters(
    queryset: QuerySet[PhoneCallRecord],
    from_date: date | None,
    to_date: date | None,
) -> QuerySet[PhoneCallRecord]:
    if from_date:
        queryset = queryset.filter(call_date__gte=from_date)
    if to_date:
        queryset = queryset.filter(call_date__lte=to_date)
    return queryset


def _apply_search_filter(
    queryset: QuerySet[PhoneCallRecord],
    query: str | None,
) -> QuerySet[PhoneCallRecord]:
    if not query:
        return queryset
    search = query.strip()
    if not search:
        return queryset

    normalized_phone = normalize_phone(search)
    # Keep each search clause unique so ranking is not accidentally weighted.
    filters = (
        Q(company__name__icontains=search)
        | Q(person__name__icontains=search)
        | Q(origin_endpoint__label__icontains=search)
        | Q(destination_endpoint__label__icontains=search)
        | Q(job__name__icontains=search)
        | Q(origin__icontains=search)
        | Q(destination__icontains=search)
        | Q(description__icontains=search)
    )
    if normalized_phone:
        filters |= Q(normalized_origin=normalized_phone) | Q(
            normalized_destination=normalized_phone
        )
    if search.isdecimal():
        filters |= Q(job__job_number=int(search))
    return queryset.filter(filters)


#: The nullable text columns of the ring-attempt identity, matched through
#: Coalesce-to-"" keys because SQL NULL never equals NULL; "" cannot collide
#: with data, which ADR 0040 bans from these columns. The non-nullable half
#: of the identity (account_code, call_datetime, duration_seconds) matches
#: directly.
_NULLABLE_IDENTITY = {
    "_twin_origin": "normalized_origin",
    "_twin_destination": "normalized_destination",
    "_twin_status": "status",
    "_twin_call_type": "call_type",
}


class _CallListAnnotations(TypedDict):
    """Queryset annotations the list serialisation reads; not model fields."""

    attempt_count: int


def _collapse_ring_attempts(
    queryset: QuerySet[PhoneCallRecord],
) -> "QuerySet[WithAnnotations[PhoneCallRecord, _CallListAnnotations]]":
    """One list row per burst of indistinguishable unrecorded ring attempts.

    The provider logs one CDR row per attempt — one real three-day pull held
    57 identical Busy pairs and 46 identical triples, differing only in the
    provider's own row id. Only rows with no recording and no job link
    collapse: a recording is evidence that only its own row holds, and a job
    link is a person's work. The smallest id survives, wearing the attempt
    count. Ingest deliberately keeps every provider row; the collapse is a
    reading of them, not a rewrite.
    """
    keys = {alias: Coalesce(column, Value("")) for alias, column in _NULLABLE_IDENTITY.items()}
    twins = (
        PhoneCallRecord.objects.annotate(**keys)
        .filter(
            recording__isnull=True,
            job__isnull=True,
            account_code=OuterRef("account_code"),
            call_datetime=OuterRef("call_datetime"),
            duration_seconds=OuterRef("duration_seconds"),
            **{alias: OuterRef(alias) for alias in _NULLABLE_IDENTITY},
        )
        .order_by()
    )
    twin_count = (
        twins.annotate(_bucket=Value(1)).values("_bucket").annotate(n=Count("*")).values("n")
    )
    return (
        queryset.annotate(**keys)
        .annotate(
            _earlier_twin=Exists(twins.filter(id__lt=OuterRef("id"))),
            attempt_count=Case(
                When(
                    recording__isnull=True,
                    job__isnull=True,
                    then=Subquery(twin_count[:1], output_field=IntegerField()),
                ),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .exclude(_earlier_twin=True, recording__isnull=True, job__isnull=True)
    )


def _filtered_call_queryset(
    filters: PhoneCallListFilters,
) -> "QuerySet[WithAnnotations[PhoneCallRecord, _CallListAnnotations]]":
    queryset = _apply_uuid_filters(_base_call_queryset(), filters)
    queryset = _apply_match_filters(queryset, filters)
    queryset = _apply_date_filters(queryset, filters.from_date, filters.to_date)
    return _collapse_ring_attempts(_apply_search_filter(queryset, filters.q))


def _recordings_by_call_id(calls: Sequence[PhoneCallRecord]) -> dict[UUID, PhoneCallRecording]:
    return {
        recording.call_id: recording
        for recording in PhoneCallRecording.objects.filter(call_id__in=[call.id for call in calls])
    }


def _attempt_count(call: PhoneCallRecord) -> int:
    """Read the ``attempt_count`` annotation ``paginate()`` erased the type of.

    ``paginate()``'s generic ``PageData[M]`` erases ``WithAnnotations`` typing
    the same way ``CompanyQuerySet`` does (see
    ``company_rest_service.annotated_with_phone``), so this validates the
    annotation actually exists on the row before casting back to it.
    """
    if "attempt_count" not in call.__dict__:
        raise RuntimeError("caller must annotate the queryset with attempt_count")
    return cast("WithAnnotations[PhoneCallRecord, _CallListAnnotations]", call).attempt_count


@router.get(
    "/phone-calls/",
    operation_id="crm_phone_calls_list",
    response=PaginatedPhoneCallRecordsOut,
    summary="List phone calls (filtered, paginated)",
)
def list_phone_calls(
    request: HttpRequest,
    filters: Query[PhoneCallListFilters],
) -> PaginatedPhoneCallRecordsOut:
    """Return the filtered call list in the standard pagination envelope."""
    _require_office_staff(request)
    page_data = paginate(
        _filtered_call_queryset(filters), page=filters.page, page_size=filters.page_size
    )
    recordings = _recordings_by_call_id(page_data.rows)
    return PaginatedPhoneCallRecordsOut(
        results=[
            PhoneCallRecordOut.from_call(
                call, recordings.get(call.id), attempt_count=_attempt_count(call)
            )
            for call in page_data.rows
        ],
        count=page_data.count,
        page=page_data.page,
        page_size=page_data.page_size,
        total_pages=page_data.total_pages,
    )


@router.get(
    "/phone-calls/{call_id}/",
    operation_id="crm_phone_calls_retrieve",
    response=PhoneCallRecordOut,
    summary="Retrieve one phone call",
)
def retrieve_phone_call(request: HttpRequest, call_id: UUID) -> PhoneCallRecordOut:
    """Single call payload, identical shape to a list row."""
    _require_office_staff(request)
    call = get_object_or_404(_base_call_queryset(), id=call_id)
    recording = PhoneCallRecording.objects.filter(call_id=call.id).first()
    return PhoneCallRecordOut.from_call(call, recording)


def _call_operation_response(
    operation: Callable[[], PhoneCallRecord],
) -> Status[PhoneCallRecordOut | OperationErrorOut]:
    """Run a phone-call service operation and serialize the updated call.

    ValueError is the services' client-error contract (400, no AppError);
    anything else follows the mandatory two-arm persistence pattern.
    """
    try:
        call = operation()
    # deliberate-swallow: the service raises ValueError carrying the message
    # meant for the user, so it becomes the 400 body verbatim; the next arm
    # persists everything that is NOT that deliberate signal
    except ValueError as exc:
        return Status(400, OperationErrorOut(message=str(exc)))
    except Exception as exc:
        persist_app_error(exc)
        raise
    recording = PhoneCallRecording.objects.filter(call_id=call.id).first()
    return Status(200, PhoneCallRecordOut.from_call(call, recording))


@router.post(
    "/phone-calls/{call_id}/job-link/",
    operation_id="linkPhoneCallJob",
    response={200: PhoneCallRecordOut, 400: OperationErrorOut},
    summary="Link a phone call to a job",
)
def link_job(
    request: HttpRequest,
    call_id: UUID,
    payload: PhoneCallJobLinkIn,
) -> Status[PhoneCallRecordOut | OperationErrorOut]:
    """Link the call to a job of the call's matched company."""
    user = _require_office_staff(request)
    return _call_operation_response(
        lambda: link_phone_call_to_job(
            call_id=call_id,
            job_id=payload.job,
            linked_by=user,
        )
    )


@router.delete(
    "/phone-calls/{call_id}/job-link/",
    operation_id="unlinkPhoneCallJob",
    response={200: PhoneCallRecordOut, 400: OperationErrorOut},
    summary="Unlink a phone call from its job",
)
def unlink_job(
    request: HttpRequest,
    call_id: UUID,
) -> Status[PhoneCallRecordOut | OperationErrorOut]:
    """Clear the call's job link."""
    _require_office_staff(request)
    return _call_operation_response(lambda: unlink_phone_call_job(call_id=call_id))


@router.post(
    "/phone-calls/{call_id}/assign-number/",
    operation_id="assignPhoneCallNumber",
    response={200: PhoneCallRecordOut, 400: OperationErrorOut},
    summary="Assign the call's external number to a company",
)
def assign_number(
    request: HttpRequest,
    call_id: UUID,
    payload: PhoneNumberAssignmentIn,
) -> Status[PhoneCallRecordOut | OperationErrorOut]:
    """Create/claim the contact method for the call's external number and rematch."""
    _require_office_staff(request)
    return _call_operation_response(
        lambda: assign_phone_number_from_call(
            call_id=call_id,
            company_id=payload.company,
            person_id=payload.person,
            label=payload.label,
            is_primary=payload.is_primary,
        )
    )


# ---------------------------------------------------------------------------
# Phone call recordings
# ---------------------------------------------------------------------------


def _recording_queryset() -> QuerySet[PhoneCallRecording]:
    return PhoneCallRecording.objects.order_by("-call__call_datetime")


@router.get(
    "/phone-call-recordings/",
    operation_id="crm_phone_call_recordings_list",
    response=list[PhoneCallRecordingOut],
    summary="List phone call recordings",
)
def list_recordings(request: HttpRequest) -> list[PhoneCallRecordingOut]:
    """All recordings, newest call first."""
    _require_office_staff(request)
    return [PhoneCallRecordingOut.from_recording(r) for r in _recording_queryset()]


@router.get(
    "/phone-call-recordings/{recording_id}/",
    operation_id="crm_phone_call_recordings_retrieve",
    response=PhoneCallRecordingOut,
    summary="Retrieve one phone call recording",
)
def retrieve_recording(request: HttpRequest, recording_id: UUID) -> PhoneCallRecordingOut:
    """Single recording payload."""
    _require_office_staff(request)
    recording = get_object_or_404(_recording_queryset(), pk=recording_id)
    return PhoneCallRecordingOut.from_recording(recording)


def _stream_recording(request: HttpRequest, recording: PhoneCallRecording) -> HttpResponseBase:
    """Open the archived file and answer with the audio or a 304 revalidation."""
    # Recordings are content-addressed, so the stored digest is a strong ETag.
    etag = f'"{recording.sha256}"' if recording.sha256 else None
    full_path = recording_file_path(recording)
    # Opened before the conditional is answered: a row whose digest
    # outlives its file must 404, not 304 the clients holding a stale copy.
    handle = full_path.open("rb")

    # RFC 9110 s13.1.2: If-None-Match is a WEAK comparison, so the validator a
    # compressing proxy weakened to W/"<sha>" still matches. Rejected the strict
    # string compare this began as: through the Vite preview proxy it answered
    # 200 and resent the audio on every replay. Django's helper owns the
    # parsing and the comparison (ADR 0032).
    conditional = get_conditional_response(request, etag=etag)
    if conditional is not None:
        handle.close()
        if etag:
            conditional["ETag"] = etag  # RFC 9110: a 304 repeats the validator
        return conditional

    response = FileResponse(handle)
    content_type, _ = mimetypes.guess_type(full_path)
    if content_type:
        response["Content-Type"] = content_type
    response["Content-Disposition"] = f'inline; filename="{recording.filename}"'
    if etag:
        response["ETag"] = etag
    return response


@router.get(
    "/phone-call-recordings/{recording_id}/download/",
    operation_id="downloadPhoneCallRecording",
    summary="Stream the archived recording audio",
)
def download_recording(request: HttpRequest, recording_id: UUID) -> HttpResponseBase:
    """Stream the local file with a content-address ETag (304 on revalidation)."""
    _require_office_staff(request)
    recording = get_object_or_404(_recording_queryset(), pk=recording_id)
    try:
        response = _stream_recording(request, recording)
    # deliberate-swallow: the recording ROW exists but its file does not, which
    # is a 404 about the file rather than a server fault — the provider prunes
    # recordings on its own schedule and the row legitimately outlives them
    except FileNotFoundError:
        return JsonResponse(
            {"status": "error", "message": "Recording file not found on disk"},
            status=404,
        )
    except Exception as exc:
        persist_app_error(exc)
        raise
    else:
        return response


@router.delete(
    "/phone-call-recordings/{recording_id}/local-file/",
    operation_id="deleteLocalPhoneCallRecording",
    response={204: None},
    summary="Delete the locally archived recording file",
)
def delete_local_file(request: HttpRequest, recording_id: UUID) -> Status[None]:
    """Superuser-only: remove the local archive copy."""
    _require_superuser(request)
    recording = get_object_or_404(_recording_queryset(), pk=recording_id)
    try:
        delete_local_recording(recording)
    except Exception as exc:
        persist_app_error(exc)
        raise
    return Status(204, None)


@router.delete(
    "/phone-call-recordings/{recording_id}/provider-file/",
    operation_id="deleteProviderPhoneCallRecording",
    response={204: None},
    summary="Delete the recording on the provider side",
)
def delete_provider_file(request: HttpRequest, recording_id: UUID) -> Status[None]:
    """Superuser-only: delete the provider-side copy (idempotent)."""
    _require_superuser(request)
    recording = get_object_or_404(_recording_queryset(), pk=recording_id)
    try:
        provider_delete_recording(recording)
    except Exception as exc:
        persist_app_error(exc)
        raise
    return Status(204, None)


# ---------------------------------------------------------------------------
# Phone endpoints (superuser admin surface)
# ---------------------------------------------------------------------------


def _endpoint_field_errors(
    instance: PhoneEndpoint | None,
    provided: dict[str, object],
) -> FieldErrors | None:
    """Validate phone endpoints at the API boundary so bad input returns 400.

    Grandfathering symmetry with PhoneEndpoint.save(): only enforced on create
    or when the number/is_active association changes.
    """
    if "number" in provided:
        # Strip the display value (normalized_number is
        # derived separately); keep the stored field whitespace-free.
        number = str(provided["number"]).strip()
        provided["number"] = number
        if not normalize_phone(number):
            return {"number": ["Phone endpoint requires a number."]}
    elif instance is not None:
        number = instance.number
    else:
        return {"number": ["Phone endpoint requires a number."]}
    normalized = normalize_phone(number)
    if normalized is None:
        return {"number": ["Phone endpoint requires a number."]}

    if "is_active" in provided:
        is_active = bool(provided["is_active"])
    elif instance is not None:
        is_active = instance.is_active
    else:
        is_active = True  # model field default

    if instance is not None and (
        normalized == instance.normalized_number and is_active == instance.is_active
    ):
        return None  # association unchanged — grandfathered, like save()

    if is_active:
        conflict = ContactMethod.conflicting_company(normalized, set())
        if conflict:
            message = (
                f"Phone number {normalized} already belongs to "
                f"{conflict.owner_display_name()} and cannot be an "
                "active internal phone endpoint."
            )
            return {"number": [message]}
    return None


_ENDPOINT_PLAIN_FIELDS = (
    "number",
    "label",
    "endpoint_type",
    "provider_account_code",
    "provider_metadata",
    "is_active",
)


def _apply_endpoint_fields(
    endpoint: PhoneEndpoint,
    provided: dict[str, object],
) -> FieldErrors | None:
    """Set provided fields on the endpoint; returns field errors for a bad staff id."""
    if "staff" in provided:
        staff_id = provided["staff"]
        if staff_id is None:
            endpoint.staff = None
        else:
            staff = Staff.objects.filter(pk=str(staff_id)).first()
            if staff is None:
                return {"staff": ["Staff not found."]}
            endpoint.staff = staff
    for field_name in _ENDPOINT_PLAIN_FIELDS:
        if field_name in provided:
            setattr(endpoint, field_name, provided[field_name])
    return None


@router.get(
    "/phone-endpoints/",
    operation_id="crm_phone_endpoints_list",
    response=list[PhoneEndpointOut],
    summary="List internal phone endpoints",
)
def list_endpoints(
    request: HttpRequest,
    is_active: bool | None = None,
) -> QuerySet[PhoneEndpoint]:
    """Endpoints ordered by type then label, optionally filtered by is_active."""
    _require_superuser(request)
    queryset = PhoneEndpoint.objects.select_related("staff").order_by("endpoint_type", "label")
    if is_active is None:
        return queryset
    return queryset.filter(is_active=is_active)


@router.post(
    "/phone-endpoints/",
    operation_id="crm_phone_endpoints_create",
    response={201: PhoneEndpointOut, 400: FieldErrors},
    summary="Create an internal phone endpoint",
)
def create_endpoint(
    request: HttpRequest,
    payload: PhoneEndpointCreateIn,
) -> Status[PhoneEndpoint | FieldErrors]:
    """Create the endpoint and queue a rematch of historical calls on its number."""
    _require_superuser(request)
    provided = payload.dict()
    errors = _endpoint_field_errors(None, provided)
    if errors:
        return Status(400, errors)
    endpoint = PhoneEndpoint()
    staff_errors = _apply_endpoint_fields(endpoint, provided)
    if staff_errors:
        return Status(400, staff_errors)
    endpoint.save()
    rematch_phone_calls_task.delay([endpoint.normalized_number])
    return Status(201, endpoint)


@router.get(
    "/phone-endpoints/{endpoint_id}/",
    operation_id="crm_phone_endpoints_retrieve",
    response=PhoneEndpointOut,
    summary="Retrieve one internal phone endpoint",
)
def retrieve_endpoint(request: HttpRequest, endpoint_id: UUID) -> PhoneEndpoint:
    """Single endpoint payload."""
    _require_superuser(request)
    return get_object_or_404(PhoneEndpoint.objects.select_related("staff"), pk=endpoint_id)


def _update_endpoint(
    endpoint_id: UUID,
    provided: dict[str, object],
) -> Status[PhoneEndpoint | FieldErrors]:
    endpoint = get_object_or_404(PhoneEndpoint.objects.select_related("staff"), pk=endpoint_id)
    errors = _endpoint_field_errors(endpoint, provided)
    if errors:
        return Status(400, errors)
    old_number = endpoint.normalized_number
    staff_errors = _apply_endpoint_fields(endpoint, provided)
    if staff_errors:
        return Status(400, staff_errors)
    endpoint.save()
    rematch_phone_calls_task.delay([old_number, endpoint.normalized_number])
    return Status(200, endpoint)


@router.put(
    "/phone-endpoints/{endpoint_id}/",
    operation_id="crm_phone_endpoints_update",
    response={200: PhoneEndpointOut, 400: FieldErrors},
    summary="Update an internal phone endpoint",
)
def update_endpoint(
    request: HttpRequest,
    endpoint_id: UUID,
    payload: PhoneEndpointPutIn,
) -> Status[PhoneEndpoint | FieldErrors]:
    """Full update; DRF semantics — absent optional fields stay unchanged."""
    _require_superuser(request)
    return _update_endpoint(endpoint_id, payload.dict(exclude_unset=True))


@router.patch(
    "/phone-endpoints/{endpoint_id}/",
    operation_id="crm_phone_endpoints_partial_update",
    response={200: PhoneEndpointOut, 400: FieldErrors},
    summary="Partially update an internal phone endpoint",
)
def partial_update_endpoint(
    request: HttpRequest,
    endpoint_id: UUID,
    payload: PhoneEndpointPatchIn,
) -> Status[PhoneEndpoint | FieldErrors]:
    """Partial update; only provided fields change."""
    _require_superuser(request)
    return _update_endpoint(endpoint_id, payload.dict(exclude_unset=True))


@router.delete(
    "/phone-endpoints/{endpoint_id}/",
    operation_id="crm_phone_endpoints_destroy",
    response={204: None},
    summary="Delete an internal phone endpoint",
)
def destroy_endpoint(request: HttpRequest, endpoint_id: UUID) -> Status[None]:
    """Delete the endpoint and queue a rematch of calls on its number."""
    _require_superuser(request)
    endpoint = get_object_or_404(PhoneEndpoint, pk=endpoint_id)
    number = endpoint.normalized_number
    endpoint.delete()
    rematch_phone_calls_task.delay([number])
    return Status(204, None)
