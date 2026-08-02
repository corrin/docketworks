"""The job domain's ninja router (thin translators over apps.job.services.job_service).

Job-core surface only (Phase 3b-1). Paths and operationIds match v1's
generated OpenAPI schema (frontend/schema.yml):

- ``/api/job/jobs/...``                     — job CRUD (delta envelope, ADR 0004),
  header, summary, basic-info, status-choices, events, timeline, undo-change,
  quote accept (v1 ``job_rest_views.py``)
- ``/api/job/jobs/delta-rejections/...``    — individual + grouped rejection
  triage (v1 ``job_rest_views.py`` + ``job_delta_rejection_grouped_view.py``)

Costing surface (Phase 3b-2):

- ``/api/job/jobs/{id}/cost_sets/...``      — cost-set retrieval, cost-line
  create, quote revisions (v1 ``job_costing_views.py`` + ``job_costline_views.py``)
- ``/api/job/cost_lines/...``               — cost-line update/delete
- ``/api/job/jobs/{id}/costs/summary/``     — per-kind cost summary
- ``/api/job/labour-subtypes/...`` and ``/api/job/jobs/{id}/labour-rates/``
  — labour subtype catalogue + per-job charge-out rates (v1 ``labour_views.py``)

Deferred from the costing surface: cost-line approve (needs purchasing's
``consume_stock`` — purchasing services sub-slice), quote apply/link/preview
(Google Sheets quote sync — importer sub-slice), timesheet repricing of
``created_from_timesheet`` lines (timesheet sub-slice; such writes fail
early with a clear error).

Later sub-slices (not here): kanban, files, workshop PDFs,
chat, importers, month-end, data-integrity.

Concurrency (ADR 0003): GETs return a strong ``ETag`` and honour
``If-None-Match`` (304). Mutations require ``If-Match`` — missing → 428 here,
mismatch → 412 via the ``PreconditionFailedError`` handler in
``apps/core/envelope.py``. ``ResourceVersionMiddleware`` mirrors ``"job:...``
ETags into ``X-Resource-Version``.

Auth per v1 ``BaseJobRestView``: reads need any authenticated staff, mutations
need office staff; the delta-rejection triage views are office-only. Success
bodies match v1; error bodies use the v2 envelope (ADR 0013).

Integration wiring (config/api.py): ``api.add_router("/", router)`` — the
paths below carry their own ``/job/`` prefix.
"""

import logging
from uuid import UUID

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth, OfficeStaffCookieJWTAuth
from apps.core.etag import generate_updated_at_etag, if_none_match_satisfied
from apps.job.models import Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.schemas import (
    CostLineCreateRequest,
    CostLineOut,
    CostLineUpdateRequest,
    CostSetOut,
    GroupedJobDeltaRejectionListResponse,
    GroupedJobDeltaRejectionResolveRequest,
    GroupedJobDeltaRejectionResolveResponse,
    JobBasicInformationResponse,
    JobCostSummaryResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobDeleteResponse,
    JobDeltaEnvelope,
    JobDeltaRejectionListResponse,
    JobDetailResponse,
    JobEventCreateRequest,
    JobEventCreateResponse,
    JobEventsResponse,
    JobHeaderResponse,
    JobLabourRateOut,
    JobLabourRatesUpdateRequest,
    JobQuoteAcceptanceResponse,
    JobStatusChoicesResponse,
    JobTimelineResponse,
    JobUndoRequest,
    LabourSubtypeManageCreateRequest,
    LabourSubtypeManageOut,
    LabourSubtypeManageUpdateRequest,
    LabourSubtypeOut,
    QuoteRevisionRequest,
    QuoteRevisionResponse,
    QuoteRevisionsListResponse,
)
from apps.job.services import job_service
from apps.job.services.job_service import CostLineWriteData, JobCreateData

logger = logging.getLogger(__name__)

router = Router()

auth = CookieJWTAuth()
office_auth = OfficeStaffCookieJWTAuth()


# ── OCC helpers (ADR 0003) ───────────────────────────────────────────────


def _job_etag(job: Job) -> str:
    return generate_updated_at_etag("job", job.id, job.updated_at)


def _current_job_etag(job_id: UUID) -> str | None:
    job = Job.objects.only("id", "updated_at").filter(id=job_id).first()
    return _job_etag(job) if job else None


def _require_if_match(request: HttpRequest) -> str:
    """Return the If-Match header or answer 428 Precondition Required."""
    if_match = request.headers.get("If-Match")
    if not if_match:
        raise HttpError(428, "Missing If-Match header (precondition required)")
    return if_match


def _set_job_etag(response: HttpResponse, job_id: UUID) -> None:
    etag = _current_job_etag(job_id)
    if etag:
        response.headers["ETag"] = etag


def _not_modified(request: HttpRequest, response: HttpResponse, etag: str | None) -> bool:
    """Answer a conditional GET: set the ETag and report If-None-Match satisfaction."""
    if etag:
        response.headers["ETag"] = etag
    if_none_match = request.headers.get("If-None-Match")
    return bool(if_none_match and etag and if_none_match_satisfied(if_none_match, etag))


def _staff(request: HttpRequest) -> Staff:
    """Narrow the authenticated user to a real Staff row (ADR 0028)."""
    auth_user: object = getattr(request, "auth", None)
    user = auth_user if isinstance(auth_user, Staff) else request.user
    if not isinstance(user, Staff):
        raise HttpError(401, "Authentication credentials were not provided.")
    return user


# ── Job CRUD ─────────────────────────────────────────────────────────────


@router.post(
    "/job/jobs/",
    auth=office_auth,
    operation_id="job_jobs_create",
    response={201: JobCreateResponse},
    summary="Create a new Job",
    tags=["Jobs"],
)
def job_jobs_create(
    request: HttpRequest, payload: JobCreateRequest, response: HttpResponse
) -> Status[dict[str, object]]:
    """Create a new Job with its initial estimate cost lines."""
    data: JobCreateData = {
        "name": payload.name,
        "company_id": payload.company_id,
        "is_urgent": payload.is_urgent,
        "estimated_materials": payload.estimated_materials,
        "estimated_time": payload.estimated_time,
    }
    if payload.description:
        data["description"] = payload.description
    if payload.order_number:
        data["order_number"] = payload.order_number
    if payload.notes:
        data["notes"] = payload.notes
    if payload.person_id:
        data["person_id"] = payload.person_id
    if payload.pricing_methodology:
        data["pricing_methodology"] = payload.pricing_methodology

    try:
        job = job_service.create_job(data, _staff(request))
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc

    response.headers["ETag"] = _job_etag(job)
    return Status(
        201,
        {
            "success": True,
            "job_id": str(job.id),
            "job_number": job.job_number,
            "message": "Job created successfully",
        },
    )


@router.get(
    "/job/jobs/status-choices/",
    auth=auth,
    operation_id="job_jobs_status_choices_retrieve",
    response=JobStatusChoicesResponse,
    summary="Fetch job status choices",
    tags=["Jobs"],
)
def job_jobs_status_choices_retrieve(request: HttpRequest) -> dict[str, dict[str, str]]:
    """Return the status choices available for jobs."""
    return {"statuses": dict(Job.JOB_STATUS_CHOICES)}


@router.get(
    "/job/jobs/{uuid:job_id}/",
    auth=auth,
    operation_id="getFullJob",
    response={200: JobDetailResponse, 304: None},
    summary="Fetch complete job data",
    tags=["Jobs"],
)
def get_full_job(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> Status[None] | dict[str, object]:
    """Fetch complete Job data for editing (conditional GET via If-None-Match)."""
    if _not_modified(request, response, _current_job_etag(job_id)):
        return Status(304, None)
    try:
        job_data = job_service.get_job_for_edit(job_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return {"success": True, "data": job_data}


def _update_job(
    request: HttpRequest, job_id: UUID, payload: JobDeltaEnvelope, response: HttpResponse
) -> dict[str, object]:
    if_match = _require_if_match(request)
    envelope = payload.model_dump()
    try:
        updated_job = job_service.update_job(
            job_id,
            envelope,
            _staff(request),
            if_match=if_match,
            request_ip=request.META.get("REMOTE_ADDR"),
        )
        # Return complete job data for frontend reactivity
        job_data = job_service.get_job_for_edit(job_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    response.headers["ETag"] = _job_etag(updated_job)
    return {"success": True, "data": job_data}


@router.put(
    "/job/jobs/{uuid:job_id}/",
    auth=office_auth,
    operation_id="job_jobs_update",
    response=JobDetailResponse,
    summary="Update Job data (autosave)",
    tags=["Jobs"],
)
def job_jobs_update(
    request: HttpRequest, job_id: UUID, payload: JobDeltaEnvelope, response: HttpResponse
) -> dict[str, object]:
    """Update Job data from a delta envelope (ADR 0004; If-Match required)."""
    return _update_job(request, job_id, payload, response)


@router.patch(
    "/job/jobs/{uuid:job_id}/",
    auth=office_auth,
    operation_id="job_jobs_partial_update",
    response=JobDetailResponse,
    summary="Partially update Job data",
    tags=["Jobs"],
)
def job_jobs_partial_update(
    request: HttpRequest, job_id: UUID, payload: JobDeltaEnvelope, response: HttpResponse
) -> dict[str, object]:
    """Apply a partial update from a delta envelope (same pipeline as PUT)."""
    return _update_job(request, job_id, payload, response)


@router.delete(
    "/job/jobs/{uuid:job_id}/",
    auth=office_auth,
    operation_id="job_jobs_destroy",
    response=JobDeleteResponse,
    summary="Delete a Job",
    tags=["Jobs"],
)
def job_jobs_destroy(request: HttpRequest, job_id: UUID) -> dict[str, object]:
    """Delete a Job if business rules allow (If-Match required)."""
    if_match = _require_if_match(request)
    try:
        result = job_service.delete_job(job_id, _staff(request), if_match=if_match)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return dict(result)


@router.get(
    "/job/jobs/{uuid:job_id}/summary/",
    auth=auth,
    operation_id="getJobSummary",
    response={200: JobDetailResponse, 304: None},
    summary="Fetch job summary (cost set totals only)",
    tags=["Jobs"],
)
def get_job_summary(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> Status[None] | dict[str, object]:
    """Fetch job data with cost-set summaries only (no cost lines or events)."""
    if _not_modified(request, response, _current_job_etag(job_id)):
        return Status(304, None)
    try:
        job_data = job_service.get_job_summary(job_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return {"success": True, "data": job_data}


@router.get(
    "/job/jobs/{uuid:job_id}/header/",
    auth=auth,
    operation_id="job_jobs_header_retrieve",
    response={200: JobHeaderResponse, 304: None},
    summary="Fetch essential job header information",
    tags=["Jobs"],
)
def job_jobs_header_retrieve(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> Status[None] | job_service.JobHeaderData:
    """Fetch essential job header data for fast initial loading."""
    job = (
        Job.objects.select_related("company", "person", "default_xero_pay_item")
        .filter(id=job_id)
        .first()
    )
    if job is None:
        # v1 mapped Job.DoesNotExist to 404 on this route.
        raise Http404(f"Job with id {job_id} not found")
    if _not_modified(request, response, _job_etag(job)):
        return Status(304, None)
    return job_service.job_header_data(job)


@router.get(
    "/job/jobs/{uuid:job_id}/basic-info/",
    auth=auth,
    operation_id="job_jobs_basic_info_retrieve",
    response={200: JobBasicInformationResponse, 304: None},
    summary="Fetch job basic information",
    tags=["Jobs"],
)
def job_jobs_basic_info_retrieve(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> Status[None] | job_service.JobBasicInformationData:
    """Fetch description, delivery date, order number and notes."""
    if not Job.objects.filter(id=job_id).exists():
        # v1 mapped Job.DoesNotExist to 404 on this route.
        raise Http404(f"Job with id {job_id} not found")
    if _not_modified(request, response, _current_job_etag(job_id)):
        return Status(304, None)
    try:
        return job_service.get_job_basic_information(job_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


# ── Events / timeline / undo ─────────────────────────────────────────────


@router.get(
    "/job/jobs/{uuid:job_id}/events/",
    auth=auth,
    operation_id="job_jobs_events_retrieve",
    response=JobEventsResponse,
    summary="Fetch job events list",
    tags=["Jobs"],
)
def job_jobs_events_retrieve(request: HttpRequest, job_id: UUID) -> dict[str, object]:
    """Fetch the job's events, newest first."""
    job = Job.objects.filter(id=job_id).first()
    if job is None:
        # v1 mapped Job.DoesNotExist to 404 on this route.
        raise Http404(f"Job with id {job_id} not found")
    events = job.events.select_related("staff").order_by("-timestamp")
    return {"events": [job_service.job_event_data(event) for event in events]}


def _check_request_debounce(
    request: HttpRequest, operation_key: str, debounce_seconds: int
) -> bool:
    """Return True when the request falls inside the debounce window (v1 behaviour)."""
    user = _staff(request)
    cache_key = f"debounce:{operation_key}:{user.id}"
    if cache.get(cache_key):
        return True
    cache.set(cache_key, True, debounce_seconds)
    return False


@router.post(
    "/job/jobs/{uuid:job_id}/events/create/",
    auth=office_auth,
    operation_id="job_rest_jobs_events_create",
    response={201: JobEventCreateResponse, 409: JobEventCreateResponse},
    summary="Add a manual event to the Job",
    tags=["Jobs"],
)
def job_rest_jobs_events_create(
    request: HttpRequest, job_id: UUID, payload: JobEventCreateRequest, response: HttpResponse
) -> Status[dict[str, object]]:
    """Add a manual event with duplicate prevention (If-Match required)."""
    if_match = _require_if_match(request)
    user = _staff(request)

    # Debounce check - prevent rapid requests
    if _check_request_debounce(request, f"add_event:{job_id}", debounce_seconds=2):
        logger.warning("Request debounced for user %s on job %s", user.email, job_id)
        raise HttpError(429, "Request too frequent. Please wait before adding another event.")

    # Additional duplicate check via cache
    description = payload.description.strip()
    duplicate_check_key = f"event_duplicate:{job_id}:{user.id}:{hash(description)}"
    if cache.get(duplicate_check_key):
        logger.warning(
            "Duplicate event prevented via cache for user %s on job %s", user.email, job_id
        )
        raise HttpError(409, "Duplicate event detected. An identical event was recently created.")

    try:
        result = job_service.add_job_event(job_id, description, user, if_match)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc

    # Set duplicate prevention cache (5 minutes)
    cache.set(duplicate_check_key, True, 300)

    _set_job_etag(response, job_id)
    body: dict[str, object] = {
        "success": result["success"],
        "event": job_service.job_event_data(result["event"]),
    }
    return Status(409 if result["duplicate_prevented"] else 201, body)


@router.get(
    "/job/jobs/{uuid:job_id}/timeline/",
    auth=auth,
    operation_id="job_jobs_timeline_retrieve",
    response=JobTimelineResponse,
    summary="Fetch unified job timeline",
    tags=["Jobs"],
)
def job_jobs_timeline_retrieve(request: HttpRequest, job_id: UUID) -> dict[str, object]:
    """Fetch the unified job timeline (events + cost lines, newest first)."""
    try:
        return {"timeline": job_service.get_job_timeline(job_id)}
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post(
    "/job/jobs/{uuid:job_id}/undo-change/",
    auth=office_auth,
    operation_id="job_jobs_undo_change_create",
    response=JobDetailResponse,
    summary="Undo a previously applied job delta",
    tags=["Jobs"],
)
def job_jobs_undo_change_create(
    request: HttpRequest, job_id: UUID, payload: JobUndoRequest, response: HttpResponse
) -> dict[str, object]:
    """Undo a recorded delta by applying its reverse envelope (If-Match required)."""
    if_match = _require_if_match(request)
    try:
        updated_job = job_service.undo_job_change(
            job_id,
            payload.change_id,
            _staff(request),
            if_match=if_match,
            undo_change_id=payload.undo_change_id,
            request_ip=request.META.get("REMOTE_ADDR"),
        )
        job_data = job_service.get_job_for_edit(job_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    response.headers["ETag"] = _job_etag(updated_job)
    return {"success": True, "data": job_data}


# ── Quote acceptance ─────────────────────────────────────────────────────


@router.post(
    "/job/jobs/{uuid:job_id}/quote/accept/",
    auth=office_auth,
    operation_id="job_jobs_quote_accept_create",
    response=JobQuoteAcceptanceResponse,
    summary="Accept a quote for the job",
    tags=["Jobs"],
)
def job_jobs_quote_accept_create(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> dict[str, object]:
    """Accept the job's quote: set acceptance date, move to approved (If-Match)."""
    if_match = _require_if_match(request)
    try:
        result = job_service.accept_quote(job_id, _staff(request), if_match=if_match)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    _set_job_etag(response, job_id)
    return dict(result)


# ── Delta rejections ─────────────────────────────────────────────────────


@router.get(
    "/job/jobs/delta-rejections/",
    auth=auth,
    operation_id="job_rest_jobs_delta_rejections_admin_list",
    response=JobDeltaRejectionListResponse,
    summary="Fetch rejected job delta envelopes (global admin view)",
    tags=["Jobs"],
)
def job_rest_jobs_delta_rejections_admin_list(
    request: HttpRequest,
    limit: int = 50,
    offset: int = 0,
    job_id: UUID | None = None,
    resolved: bool | None = None,
) -> job_service.DeltaRejectionListData:
    """List delta rejections across all jobs, optionally filtered."""
    return job_service.list_job_delta_rejections(
        job_id=job_id, resolved=resolved, limit=limit, offset=offset
    )


@router.get(
    "/job/jobs/{uuid:job_id}/delta-rejections/",
    auth=auth,
    operation_id="job_rest_job_delta_rejections_list",
    response=JobDeltaRejectionListResponse,
    summary="Fetch delta rejections recorded for this job",
    tags=["Jobs"],
)
def job_rest_job_delta_rejections_list(
    request: HttpRequest, job_id: UUID, limit: int = 50, offset: int = 0
) -> job_service.DeltaRejectionListData:
    """List delta rejections for one job."""
    if not Job.objects.filter(id=job_id).exists():
        raise HttpError(400, f"Job with id {job_id} not found")
    return job_service.list_job_delta_rejections(job_id=job_id, limit=limit, offset=offset)


@router.get(
    "/job/jobs/delta-rejections/grouped/",
    auth=office_auth,
    operation_id="job_jobs_delta_rejections_grouped_retrieve",
    response=GroupedJobDeltaRejectionListResponse,
    summary="Fetch delta rejections grouped by reason",
    tags=["Jobs"],
)
def job_jobs_delta_rejections_grouped_retrieve(
    request: HttpRequest,
    limit: int = 50,
    offset: int = 0,
    job_id: str | None = None,
    resolved: bool | None = None,
) -> job_service.GroupedDeltaRejectionListData:
    """Group delta rejections by reason for triage."""
    return job_service.list_grouped_job_delta_rejections(
        limit=limit, offset=offset, job_id=job_id, resolved=resolved
    )


@router.post(
    "/job/jobs/delta-rejections/grouped/mark_resolved/",
    auth=office_auth,
    operation_id="job_jobs_delta_rejections_grouped_mark_resolved_create",
    response=GroupedJobDeltaRejectionResolveResponse,
    summary="Resolve a delta-rejection reason group",
    tags=["Jobs"],
)
def job_jobs_delta_rejections_grouped_mark_resolved_create(
    request: HttpRequest, payload: GroupedJobDeltaRejectionResolveRequest
) -> dict[str, int]:
    """Resolve every rejection in the fingerprinted reason group."""
    updated = job_service.mark_job_delta_rejection_group_resolved_by_fingerprint(
        payload.fingerprint, _staff(request)
    )
    return {"updated": updated}


@router.post(
    "/job/jobs/delta-rejections/grouped/mark_unresolved/",
    auth=office_auth,
    operation_id="job_jobs_delta_rejections_grouped_mark_unresolved_create",
    response=GroupedJobDeltaRejectionResolveResponse,
    summary="Reopen a delta-rejection reason group",
    tags=["Jobs"],
)
def job_jobs_delta_rejections_grouped_mark_unresolved_create(
    request: HttpRequest, payload: GroupedJobDeltaRejectionResolveRequest
) -> dict[str, int]:
    """Reopen every rejection in the fingerprinted reason group."""
    updated = job_service.mark_job_delta_rejection_group_unresolved_by_fingerprint(
        payload.fingerprint, _staff(request)
    )
    return {"updated": updated}


# ── Costing: cost sets, cost lines, quote revisions, costs summary ───────


def _validation_message(exc: DjangoValidationError) -> str:
    """Flatten a model ValidationError into the v1-style single message string."""
    return "; ".join(exc.messages)


def _get_job_or_404(job_id: UUID) -> Job:
    return get_object_or_404(Job, id=job_id)


@router.get(
    "/job/jobs/{uuid:job_id}/cost_sets/quote/revise/",
    auth=auth,
    operation_id="job_jobs_cost_sets_quote_revise_retrieve",
    response=QuoteRevisionsListResponse,
    summary="List archived quote revisions",
    tags=["job"],
)
def job_jobs_cost_sets_quote_revise_retrieve(
    request: HttpRequest, job_id: UUID
) -> job_service.QuoteRevisionsListData:
    """Return the archived quote revisions stored in the quote CostSet summary."""
    job = _get_job_or_404(job_id)
    revisions = job_service.list_quote_revisions(job)
    if revisions is None:
        raise HttpError(404, "No quote found for this job.")
    return revisions


@router.post(
    "/job/jobs/{uuid:job_id}/cost_sets/quote/revise/",
    auth=office_auth,
    operation_id="job_jobs_cost_sets_quote_revise_create",
    response=QuoteRevisionResponse,
    summary="Create a new quote revision",
    tags=["job"],
)
def job_jobs_cost_sets_quote_revise_create(
    request: HttpRequest, job_id: UUID, payload: QuoteRevisionRequest
) -> job_service.QuoteRevisionResultData:
    """Archive the current quote cost lines and start a fresh quote revision."""
    job = _get_job_or_404(job_id)
    if job.get_latest("quote") is None:
        raise HttpError(404, "No quote found for this job. Cannot create revision.")
    try:
        return job_service.create_quote_revision(job, payload.reason, _staff(request))
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get(
    "/job/jobs/{uuid:job_id}/cost_sets/{kind}/",
    auth=auth,
    operation_id="job_jobs_cost_sets_retrieve",
    response=CostSetOut,
    summary="Fetch the latest cost set of a kind",
    tags=["job"],
)
def job_jobs_cost_sets_retrieve(
    request: HttpRequest, job_id: UUID, kind: str
) -> job_service.CostSetData:
    """Return the latest CostSet of ``kind`` (estimate|quote|actual) for the job."""
    job = _get_job_or_404(job_id)
    try:
        cost_set = job_service.get_latest_cost_set(job, kind)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    if cost_set is None:
        raise HttpError(404, f"No {kind} cost set found for this job")
    return job_service.cost_set_data(cost_set)


def _create_cost_line(
    request: HttpRequest, job_id: UUID, kind: str, payload: CostLineCreateRequest
) -> job_service.CostLineData:
    staff = _staff(request)
    if kind != "actual" and not staff.is_office_staff:
        raise HttpError(403, "Only office staff can manage non-actual cost sets")
    job = _get_job_or_404(job_id)
    data: CostLineWriteData = {
        "kind": payload.kind,
        "desc": payload.desc,
        "quantity": payload.quantity,
        "unit_cost": payload.unit_cost,
        "unit_rev": payload.unit_rev,
        "accounting_date": payload.accounting_date,
        "ext_refs": payload.ext_refs,
        "meta": payload.meta,
        "xero_pay_item": payload.xero_pay_item,
        "staff": payload.staff,
        "labour_subtype": payload.labour_subtype,
    }
    try:
        line = job_service.create_cost_line(job, kind, data, staff)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    return job_service.cost_line_data(line)


@router.post(
    "/job/jobs/{uuid:job_id}/cost_sets/actual/cost_lines/",
    auth=auth,
    operation_id="job_jobs_cost_sets_actual_cost_lines_create",
    response={201: CostLineOut},
    summary="Create a cost line on the actual cost set",
    tags=["job"],
)
def job_jobs_cost_sets_actual_cost_lines_create(
    request: HttpRequest, job_id: UUID, payload: CostLineCreateRequest
) -> Status[job_service.CostLineData]:
    """Create a cost line on the job's actual cost set (v1 legacy route)."""
    return Status(201, _create_cost_line(request, job_id, "actual", payload))


@router.post(
    "/job/jobs/{uuid:job_id}/cost_sets/{kind}/cost_lines/",
    auth=auth,
    operation_id="job_jobs_cost_sets_cost_lines_create",
    response={201: CostLineOut},
    summary="Create a cost line on the given cost set",
    tags=["job"],
)
def job_jobs_cost_sets_cost_lines_create(
    request: HttpRequest, job_id: UUID, kind: str, payload: CostLineCreateRequest
) -> Status[job_service.CostLineData]:
    """Create a cost line on the job's ``kind`` cost set (office staff for non-actual)."""
    return Status(201, _create_cost_line(request, job_id, kind, payload))


def _collect_costline_patch_values(
    payload: CostLineUpdateRequest, provided: set[str], data: CostLineWriteData
) -> None:
    """Collect the provided scalar cost-line fields into ``data``."""
    if "kind" in provided and payload.kind is not None:
        data["kind"] = payload.kind
    if "desc" in provided:
        data["desc"] = payload.desc
    if "quantity" in provided and payload.quantity is not None:
        data["quantity"] = payload.quantity
    if "unit_cost" in provided and payload.unit_cost is not None:
        data["unit_cost"] = payload.unit_cost
    if "unit_rev" in provided and payload.unit_rev is not None:
        data["unit_rev"] = payload.unit_rev
    if "accounting_date" in provided and payload.accounting_date is not None:
        data["accounting_date"] = payload.accounting_date


def _collect_costline_patch_refs(
    payload: CostLineUpdateRequest, provided: set[str], data: CostLineWriteData
) -> None:
    """Collect the provided JSON/FK cost-line fields into ``data``."""
    if "ext_refs" in provided and payload.ext_refs is not None:
        data["ext_refs"] = payload.ext_refs
    if "meta" in provided and payload.meta is not None:
        data["meta"] = payload.meta
    if "xero_pay_item" in provided:
        data["xero_pay_item"] = payload.xero_pay_item
    if "staff" in provided:
        data["staff"] = payload.staff
    if "labour_subtype" in provided:
        data["labour_subtype"] = payload.labour_subtype


def _costline_patch_data(payload: CostLineUpdateRequest) -> CostLineWriteData:
    """Collect only the provided fields (partial-update semantics, v1 partial=True)."""
    provided = payload.model_fields_set
    data: CostLineWriteData = {}
    _collect_costline_patch_values(payload, provided, data)
    _collect_costline_patch_refs(payload, provided, data)
    return data


@router.patch(
    "/job/cost_lines/{uuid:cost_line_id}/",
    auth=auth,
    operation_id="job_cost_lines_partial_update",
    response=CostLineOut,
    summary="Update a cost line",
    tags=["job"],
)
def job_cost_lines_partial_update(
    request: HttpRequest, cost_line_id: UUID, payload: CostLineUpdateRequest
) -> job_service.CostLineData:
    """Update a cost line from a partial payload, adjusting linked stock on quantity change."""
    line = get_object_or_404(CostLine, id=cost_line_id)
    if line.cost_set.kind != "actual" and not _staff(request).is_office_staff:
        raise HttpError(403, "Only office staff can modify non-actual cost lines")
    try:
        updated = job_service.update_cost_line(line, _costline_patch_data(payload))
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    return job_service.cost_line_data(updated)


@router.delete(
    "/job/cost_lines/{uuid:cost_line_id}/delete/",
    auth=auth,
    operation_id="job_cost_lines_delete_destroy",
    response={204: None},
    summary="Delete a cost line",
    tags=["job"],
)
def job_cost_lines_delete_destroy(request: HttpRequest, cost_line_id: UUID) -> Status[None]:
    """Delete a cost line, returning any consumed stock to inventory."""
    line = get_object_or_404(CostLine, id=cost_line_id)
    if line.cost_set.kind != "actual" and not _staff(request).is_office_staff:
        raise HttpError(403, "Only office staff can delete non-actual cost lines")
    job_service.delete_cost_line(line)
    return Status(204, None)


@router.get(
    "/job/jobs/{uuid:job_id}/costs/summary/",
    auth=auth,
    operation_id="job_jobs_costs_summary_retrieve",
    response={200: JobCostSummaryResponse, 304: None},
    summary="Fetch job cost summary across all cost sets",
    tags=["Jobs"],
)
def job_jobs_costs_summary_retrieve(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> Status[None] | job_service.JobCostSummaryData:
    """Fetch per-kind cost summaries (conditional GET via If-None-Match, as v1)."""
    job = _get_job_or_404(job_id)
    if _not_modified(request, response, _job_etag(job)):
        return Status(304, None)
    return job_service.get_job_costs_summary(job)


# ── Labour subtypes and job labour rates ─────────────────────────────────


@router.get(
    "/job/labour-subtypes/",
    auth=auth,
    operation_id="job_labour_subtypes_list",
    response=list[LabourSubtypeOut],
    summary="List active labour subtypes",
    tags=["job"],
)
def job_labour_subtypes_list(request: HttpRequest) -> list[job_service.LabourSubtypeData]:
    """List active labour subtypes (dropdowns, rate displays)."""
    return [
        job_service.labour_subtype_data(subtype)
        for subtype in LabourSubtype.objects.filter(is_active=True)
    ]


@router.get(
    "/job/labour-subtypes/manage/",
    auth=office_auth,
    operation_id="job_labour_subtypes_manage_list",
    response=list[LabourSubtypeManageOut],
    summary="List all labour subtypes (management)",
    tags=["job"],
)
def job_labour_subtypes_manage_list(
    request: HttpRequest,
) -> list[job_service.LabourSubtypeManageData]:
    """List all labour subtypes including inactive ones (office staff)."""
    return [
        job_service.labour_subtype_manage_data(subtype) for subtype in LabourSubtype.objects.all()
    ]


@router.post(
    "/job/labour-subtypes/manage/",
    auth=office_auth,
    operation_id="job_labour_subtypes_manage_create",
    response={201: LabourSubtypeManageOut},
    summary="Create a labour subtype",
    tags=["job"],
)
def job_labour_subtypes_manage_create(
    request: HttpRequest, payload: LabourSubtypeManageCreateRequest
) -> Status[job_service.LabourSubtypeManageData]:
    """Create a labour subtype; an active one is backfilled onto every job."""
    data: job_service.LabourSubtypeWriteData = {
        "name": payload.name,
        "display_order": payload.display_order,
        "is_active": payload.is_active,
        "is_workshop": payload.is_workshop,
        "counts_for_scheduling": payload.counts_for_scheduling,
        "default_charge_out_rate": payload.default_charge_out_rate,
    }
    try:
        subtype = job_service.create_labour_subtype(data)
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    return Status(201, job_service.labour_subtype_manage_data(subtype))


@router.get(
    "/job/labour-subtypes/manage/{uuid:subtype_id}/",
    auth=office_auth,
    operation_id="job_labour_subtypes_manage_retrieve",
    response=LabourSubtypeManageOut,
    summary="Fetch one labour subtype (management)",
    tags=["job"],
)
def job_labour_subtypes_manage_retrieve(
    request: HttpRequest, subtype_id: UUID
) -> job_service.LabourSubtypeManageData:
    """Fetch one labour subtype for the management UI."""
    subtype = get_object_or_404(LabourSubtype, pk=subtype_id)
    return job_service.labour_subtype_manage_data(subtype)


@router.patch(
    "/job/labour-subtypes/manage/{uuid:subtype_id}/",
    auth=office_auth,
    operation_id="job_labour_subtypes_manage_partial_update",
    response=LabourSubtypeManageOut,
    summary="Update a labour subtype",
    tags=["job"],
)
def job_labour_subtypes_manage_partial_update(
    request: HttpRequest, subtype_id: UUID, payload: LabourSubtypeManageUpdateRequest
) -> job_service.LabourSubtypeManageData:
    """Update a labour subtype (no delete — deactivate instead, as v1)."""
    get_object_or_404(LabourSubtype, pk=subtype_id)
    provided = payload.model_fields_set
    data: job_service.LabourSubtypeWriteData = {}
    if "name" in provided and payload.name is not None:
        data["name"] = payload.name
    if "display_order" in provided and payload.display_order is not None:
        data["display_order"] = payload.display_order
    if "is_active" in provided and payload.is_active is not None:
        data["is_active"] = payload.is_active
    if "is_workshop" in provided and payload.is_workshop is not None:
        data["is_workshop"] = payload.is_workshop
    if "counts_for_scheduling" in provided and payload.counts_for_scheduling is not None:
        data["counts_for_scheduling"] = payload.counts_for_scheduling
    if "default_charge_out_rate" in provided and payload.default_charge_out_rate is not None:
        data["default_charge_out_rate"] = payload.default_charge_out_rate
    try:
        subtype = job_service.update_labour_subtype(subtype_id, data)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    return job_service.labour_subtype_manage_data(subtype)


@router.get(
    "/job/jobs/{uuid:job_id}/labour-rates/",
    auth=office_auth,
    operation_id="job_jobs_labour_rates_list",
    response=list[JobLabourRateOut],
    summary="Fetch a job's labour rates",
    tags=["job"],
)
def job_jobs_labour_rates_list(
    request: HttpRequest, job_id: UUID
) -> list[job_service.JobLabourRateData]:
    """Read the job's per-subtype charge-out rates (office staff, as v1)."""
    job = _get_job_or_404(job_id)
    return job_service.get_job_labour_rates(job)


@router.patch(
    "/job/jobs/{uuid:job_id}/labour-rates/",
    auth=office_auth,
    operation_id="job_jobs_labour_rates_partial_update",
    response=list[JobLabourRateOut],
    summary="Update a job's labour rates",
    tags=["job"],
)
def job_jobs_labour_rates_partial_update(
    request: HttpRequest, job_id: UUID, payload: JobLabourRatesUpdateRequest
) -> list[job_service.JobLabourRateData]:
    """Update the job's per-subtype charge-out rates, recording one job event."""
    job = _get_job_or_404(job_id)
    entries: list[job_service.JobLabourRateUpdateEntryData] = [
        {"labour_subtype": entry.labour_subtype, "charge_out_rate": entry.charge_out_rate}
        for entry in payload.rates
    ]
    try:
        return job_service.update_job_labour_rates(job, entries, _staff(request))
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
