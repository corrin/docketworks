"""Thin HTTP translators for the job domain.

The router exposes job CRUD, delta-rejection triage, costing, labour rates,
kanban, staff assignment, files, and PDFs under ``/api/job/``.

Cost lines carrying ``meta.created_from_timesheet`` are repriced through
``apps.job.services.time_entry_rates`` — the ONE rate-resolution pipeline
(ADR 0039), shared with the timesheet surfaces in ``apps.timesheet``.

Approving a material cost line consumes its referenced stock through
``apps.purchasing.services.stock_service.consume_stock`` (the ONE stock
consumption implementation, ADR 0039). Quote apply/link/preview remains deferred
to the Google Sheets importer slice.

``/api/job/month-end/`` exposes special-job and stock review data and can roll
a new empty actual cost set for each selected job. Chat, importers,
data-integrity, and the workshop kanban remain later slices.

Concurrency (ADR 0003): GETs return a strong ``ETag`` and honour
``If-None-Match`` (304). Mutations require ``If-Match`` — missing → 428 here,
mismatch → 412 via the ``PreconditionFailedError`` handler in
``apps/core/envelope.py``. ``ResourceVersionMiddleware`` mirrors ``"job:...``
ETags into ``X-Resource-Version``.

Reads require authenticated staff; mutations and delta-rejection triage require
office staff. Error bodies use the standard envelope from ADR 0013.

Integration wiring (config/api.py): ``api.add_router("/", router)`` — the
paths below carry their own ``/job/`` prefix.
"""

import hashlib
import logging
import mimetypes
from pathlib import Path
from uuid import UUID

from django.core.cache import BaseCache, caches
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File as NinjaFile
from ninja import Form, Router, UploadedFile
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth, OfficeStaffCookieJWTAuth
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.etag import generate_updated_at_etag, if_none_match_satisfied
from apps.job.models import Job, JobFile, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.schemas import (
    AdvancedSearchResponse,
    AssignJobRequest,
    AssignJobResponse,
    CostLineApprovalResponse,
    CostLineCreateRequest,
    CostLineOut,
    CostLineUpdateRequest,
    CostSetOut,
    FetchAllJobsResponse,
    FetchJobsByColumnResponse,
    FetchJobsResponse,
    FetchStatusValuesResponse,
    FinishJobSummaryOut,
    GroupedJobDeltaRejectionListResponse,
    GroupedJobDeltaRejectionResolveRequest,
    GroupedJobDeltaRejectionResolveResponse,
    JobBasicInformationResponse,
    JobCompletionChecklistOut,
    JobCompletionChecklistPatchIn,
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
    JobFileOut,
    JobFileUpdateRequest,
    JobFileUpdateSuccessResponse,
    JobFileUploadPartialResponse,
    JobFileUploadSuccessResponse,
    JobFinishResponse,
    JobHeaderResponse,
    JobInvoiceOut,
    JobInvoicesResponse,
    JobLabourRateOut,
    JobLabourRatesUpdateRequest,
    JobQuoteAcceptanceResponse,
    JobQuoteResponse,
    JobReorderRequest,
    JobStatusChoicesResponse,
    JobStatusUpdateRequest,
    JobTimelineResponse,
    JobUndoRequest,
    KanbanChangesResponse,
    KanbanSuccessResponse,
    LabourSubtypeManageCreateRequest,
    LabourSubtypeManageOut,
    LabourSubtypeManageUpdateRequest,
    LabourSubtypeOut,
    MonthEndGetResponse,
    MonthEndPostRequest,
    MonthEndPostResponse,
    QuoteRevisionRequest,
    QuoteRevisionResponse,
    QuoteRevisionsListResponse,
)
from apps.job.services import file_service, job_service, kanban_service, month_end_service
from apps.job.services.delivery_docket_service import generate_delivery_docket
from apps.job.services.job_service import CostLineWriteData, JobCreateData
from apps.job.services.kanban_service import KanbanService
from apps.job.services.workshop_pdf_service import create_workshop_pdf
from apps.job.tasks import create_job_file_thumbnail_task
from apps.purchasing.models import Stock
from apps.purchasing.services.stock_service import consume_stock

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
        # Object lookup misses are a 404 contract on this route.
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
        # Object lookup misses are a 404 contract on this route.
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
        # Object lookup misses are a 404 contract on this route.
        raise Http404(f"Job with id {job_id} not found")
    events = job.events.select_related("staff").order_by("-timestamp")
    return {"events": [job_service.job_event_data(event) for event in events]}


def _dedup_cache() -> BaseCache:
    """Return the cache duplicate suppression consults.

    Shared, because suppression only suppresses while every process reads the
    same record: on the per-process default the second of two identical
    requests is caught when it lands on the same gunicorn worker and sails
    through when it does not, which is a coin toss rather than a guard.

    Resolved per call because Django's handler is per-thread and drops its
    instances on teardown.
    """
    return caches["shared"]


def _stable_key(text: str) -> str:
    """Derive a key for `text` that is identical in every process, and after a restart.

    ``hash()`` is not: Python salts str hashing per process, so two workers
    derive different keys for identical text and neither sees the other's
    entry — the duplicate check silently passed everything it was meant to
    catch.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _check_request_debounce(
    request: HttpRequest, operation_key: str, debounce_seconds: int
) -> bool:
    """Return True when the request falls inside the debounce window."""
    user = _staff(request)
    cache_key = f"debounce:{operation_key}:{user.id}"
    if _dedup_cache().get(cache_key):
        return True
    _dedup_cache().set(cache_key, True, debounce_seconds)
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
    duplicate_check_key = f"event_duplicate:{job_id}:{user.id}:{_stable_key(description)}"
    if _dedup_cache().get(duplicate_check_key):
        logger.warning(
            "Duplicate event prevented via cache for user %s on job %s", user.email, job_id
        )
        raise HttpError(409, "Duplicate event detected. An identical event was recently created.")

    try:
        result = job_service.add_job_event(job_id, description, user, if_match)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc

    # Set duplicate prevention cache (5 minutes)
    _dedup_cache().set(duplicate_check_key, True, 300)

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


@router.get(
    "/job/jobs/{uuid:job_id}/quote/",
    auth=auth,
    operation_id="job_jobs_quote_retrieve",
    response=JobQuoteResponse,
    summary="Fetch the job's Xero quote",
    tags=["Jobs"],
)
def job_jobs_quote_retrieve(
    request: HttpRequest, job_id: UUID
) -> dict[str, job_service.QuoteData | None]:
    """Return the job's Xero quote header; ``quote`` is null when none exists.

    Plain GET, deliberately not a conditional-GET on the job ETag: nothing
    external holds this URL, and a 304-with-empty-body reads as "no quote"
    to an axios/TanStack consumer.
    """
    return {"quote": job_service.get_job_xero_quote(_get_job_or_404(job_id))}


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
    job_id: UUID | None = None,
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
    """Flatten a model ValidationError into the API's single message string."""
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
    # Validate kind before the job lookup: invalid kind answers 400 even
    # when the job is also unknown (adversarial review 2026-08-02).
    if kind not in job_service.COST_SET_KINDS:
        raise HttpError(
            400, f"Invalid kind. Must be one of: {', '.join(job_service.COST_SET_KINDS)}"
        )
    job = _get_job_or_404(job_id)
    cost_set = job_service.get_latest_cost_set(job, kind)
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
    """Create a cost line on the job's actual cost set."""
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
    # No `is not None` guards: the schema rejects null on the non-nullable
    # fields now, so a null that used to be dropped here (200, nothing changed)
    # is a 422 before the handler runs. Presence is the only question left.
    if "kind" in provided:
        data["kind"] = payload.kind
    if "desc" in provided:
        data["desc"] = payload.desc
    if "quantity" in provided:
        data["quantity"] = payload.quantity
    if "unit_cost" in provided:
        data["unit_cost"] = payload.unit_cost
    if "unit_rev" in provided:
        data["unit_rev"] = payload.unit_rev
    if "accounting_date" in provided:
        data["accounting_date"] = payload.accounting_date


def _collect_costline_patch_refs(
    payload: CostLineUpdateRequest, provided: set[str], data: CostLineWriteData
) -> None:
    """Collect the provided JSON/FK cost-line fields into ``data``."""
    if "ext_refs" in provided:
        data["ext_refs"] = payload.ext_refs
    if "meta" in provided:
        data["meta"] = payload.meta
    if "xero_pay_item" in provided:
        data["xero_pay_item"] = payload.xero_pay_item
    if "staff" in provided:
        data["staff"] = payload.staff
    if "labour_subtype" in provided:
        data["labour_subtype"] = payload.labour_subtype


def _costline_patch_data(payload: CostLineUpdateRequest) -> CostLineWriteData:
    """Collect only the fields provided by a partial update."""
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


@router.post(
    "/job/cost_lines/{uuid:cost_line_id}/approve/",
    auth=office_auth,
    operation_id="approveCostLine",
    response=CostLineApprovalResponse,
    summary="Approve a cost line",
    tags=["job"],
)
def approve_cost_line(request: HttpRequest, cost_line_id: UUID) -> dict[str, object]:
    """Approve a workshop-entered cost line (office staff only).

    A material line carrying ``ext_refs.stock_id`` is approved by actually
    consuming that stock — ``apps.purchasing.services.stock_service.consume_stock``
    reprices the line from the stock row and draws the quantity down. Everything
    else just flips ``approved``.
    """
    line = get_object_or_404(CostLine.objects.select_related("cost_set__job"), id=cost_line_id)
    if line.approved:
        raise HttpError(400, "Line is already approved")

    if line.kind != "material":
        line.approved = True
        line.save(update_fields=["approved", "updated_at"])
        return {
            "success": True,
            "message": "Line approved successfully",
            "line": job_service.cost_line_data(line),
        }

    stock_id = line.ext_refs.get("stock_id")
    if not stock_id:
        raise HttpError(400, "Line is missing item code")
    stock = get_object_or_404(Stock, id=stock_id)
    try:
        approved = consume_stock(
            item=stock,
            job=line.cost_set.job,
            qty=line.quantity,
            user=_staff(request),
            line=line,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return {
        "success": True,
        "message": "Line approved successfully",
        "remaining_quantity": stock.quantity,
        "line": job_service.cost_line_data(approved),
    }


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
    """Fetch per-kind cost summaries with conditional GET support."""
    job = _get_job_or_404(job_id)
    if _not_modified(request, response, _job_etag(job)):
        return Status(304, None)
    return job_service.get_job_costs_summary(job)


# ── Finish Job workspace + invoices ──────────────────────────────────────


def _finish_job_payload(job: Job) -> JobFinishResponse:
    # Call-time import: accounting is a sibling domain app; importing at
    # module scope would create a cycle through apps.accounting.services,
    # which imports apps.job.models.
    from apps.accounting.services.finish_job_summary import (  # noqa: PLC0415
        build_finish_job_summary,
    )

    summary = build_finish_job_summary(job)
    return JobFinishResponse(
        summary=FinishJobSummaryOut(
            job_value_excl_gst=summary.job_value_excl_gst,
            valid_invoiced_excl_gst=summary.valid_invoiced_excl_gst,
            outstanding_invoiced_incl_gst=summary.outstanding_invoiced_incl_gst,
            remaining_to_invoice_excl_gst=summary.remaining_to_invoice_excl_gst,
            remaining_gst=summary.remaining_gst,
            remaining_to_invoice_incl_gst=summary.remaining_to_invoice_incl_gst,
            total_to_pay_incl_gst=summary.total_to_pay_incl_gst,
            over_invoiced_excl_gst=summary.over_invoiced_excl_gst,
        ),
        checklist=JobCompletionChecklistOut(
            foreman_signed_off=job.foreman_signed_off,
            timesheets_collected=job.timesheets_collected,
            materials_checked=job.materials_checked,
            customer_called=job.customer_called,
            released=job.released,
        ),
    )


def _job_for_finish(job_id: UUID) -> Job:
    from apps.accounting.services.invoice_calculation import (  # noqa: PLC0415
        get_job_for_invoice_calculation,
    )

    try:
        return get_job_for_invoice_calculation(job_id)
    except Job.DoesNotExist as exc:
        raise HttpError(404, f"Job with ID {job_id} not found.") from exc


@router.get(
    "/job/jobs/{uuid:job_id}/finish/",
    auth=auth,
    operation_id="job_jobs_finish_retrieve",
    response=JobFinishResponse,
    summary="Fetch the Finish Job balance and completion checklist",
    tags=["Jobs"],
)
def job_jobs_finish_retrieve(request: HttpRequest, job_id: UUID) -> JobFinishResponse:
    """Return the authoritative customer balance plus the front-desk checklist.

    Deliberately not ETagged on the job. The balance moves when invoices
    change, and an invoice arriving from Xero does not touch
    ``job.updated_at``, so a job-derived ETag would answer 304 while showing
    a customer the wrong amount to pay.
    """
    return _finish_job_payload(_job_for_finish(job_id))


@router.patch(
    "/job/jobs/{uuid:job_id}/finish/",
    auth=auth,
    operation_id="job_jobs_finish_partial_update",
    response=JobFinishResponse,
    summary="Update completion checklist items",
    tags=["Jobs"],
)
def job_jobs_finish_partial_update(
    request: HttpRequest, job_id: UUID, payload: JobCompletionChecklistPatchIn
) -> JobFinishResponse:
    """Tick or untick checklist items; each change lands in the job history."""
    job = _job_for_finish(job_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        job = job_service.update_completion_checklist(job, updates, _staff(request))
    return _finish_job_payload(job)


@router.get(
    "/job/jobs/{uuid:job_id}/invoices/",
    auth=auth,
    operation_id="job_jobs_invoices_retrieve",
    response={200: JobInvoicesResponse, 304: None},
    summary="List the Xero invoices attached to a job",
    tags=["Jobs"],
)
def job_jobs_invoices_retrieve(
    request: HttpRequest, job_id: UUID, response: HttpResponse
) -> Status[None] | JobInvoicesResponse:
    """Return the job's invoice mirror rows, with conditional GET support.

    The invoice push busts the job ETag (its persistence path saves the job),
    so this cache key does move when an invoice is created locally.
    """
    job = _get_job_or_404(job_id)
    if _not_modified(request, response, _job_etag(job)):
        return Status(304, None)
    return JobInvoicesResponse(
        invoices=[
            JobInvoiceOut(
                id=invoice.id,
                xero_id=invoice.xero_id,
                number=invoice.number,
                status=invoice.status,
                date=invoice.date,
                due_date=invoice.due_date,
                total_excl_tax=float(invoice.total_excl_tax),
                total_incl_tax=float(invoice.total_incl_tax),
                amount_due=float(invoice.amount_due),
                tax=float(invoice.tax),
                online_url=invoice.online_url,
            )
            for invoice in job.invoices.all()
        ]
    )


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
    """Update a labour subtype; deactivate rather than delete it."""
    get_object_or_404(LabourSubtype, pk=subtype_id)
    provided = payload.model_fields_set
    data: job_service.LabourSubtypeWriteData = {}
    if "name" in provided:
        data["name"] = payload.name
    if "display_order" in provided:
        data["display_order"] = payload.display_order
    if "is_active" in provided:
        data["is_active"] = payload.is_active
    if "is_workshop" in provided:
        data["is_workshop"] = payload.is_workshop
    if "counts_for_scheduling" in provided:
        data["counts_for_scheduling"] = payload.counts_for_scheduling
    if "default_charge_out_rate" in provided:
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
    """Read the job's per-subtype charge-out rates (office staff only)."""
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


# ── Kanban ───────────────────────────────────────────────────────────────


@router.get(
    "/job/jobs/fetch-all/",
    auth=auth,
    operation_id="job_jobs_fetch_all_retrieve",
    response=FetchAllJobsResponse,
    summary="Fetch all jobs for the Kanban board",
    tags=["job"],
)
def job_jobs_fetch_all_retrieve(request: HttpRequest) -> dict[str, object]:
    """Fetch all active jobs plus the 50 newest archived jobs."""
    active_jobs = KanbanService.get_all_active_jobs()
    archived_jobs = KanbanService.get_archived_jobs(50)
    return {
        "success": True,
        "active_jobs": KanbanService.serialize_jobs_for_api(active_jobs),
        "archived_jobs": KanbanService.serialize_jobs_for_api(archived_jobs),
        "total_archived": Job.objects.filter(status="archived").count(),
    }


@router.get(
    "/job/jobs/fetch/{status}/",
    auth=auth,
    operation_id="job_jobs_fetch_retrieve",
    response=FetchJobsResponse,
    summary="Fetch jobs by status with optional search",
    tags=["job"],
)
def job_jobs_fetch_retrieve(
    request: HttpRequest, status: str, search: str = ""
) -> dict[str, object]:
    """Fetch jobs in one status column, optionally filtered by search terms."""
    search_terms = search.strip().split() if search.strip() else []
    jobs = KanbanService.get_jobs_by_status(status, search_terms, request=request)
    job_data = KanbanService.serialize_jobs_for_api(jobs)
    return {
        "success": True,
        "jobs": job_data,
        "total": Job.objects.filter(status=status).count(),
        "filtered_count": len(job_data),
    }


@router.get(
    "/job/jobs/fetch-by-column/{column_id}/",
    auth=auth,
    operation_id="job_jobs_fetch_by_column_retrieve",
    response=FetchJobsByColumnResponse,
    summary="Fetch jobs by kanban column",
    tags=["job"],
)
def job_jobs_fetch_by_column_retrieve(
    request: HttpRequest, column_id: str, max_jobs: int = 100, search: str = ""
) -> kanban_service.KanbanColumnJobsData:
    """Fetch jobs for one kanban column (categorization taxonomy)."""
    return KanbanService.get_jobs_by_kanban_column(column_id, max_jobs, search, request=request)


@router.get(
    "/job/jobs/kanban-changes/",
    auth=auth,
    operation_id="getKanbanChanges",
    response=KanbanChangesResponse,
    summary="Fetch changed kanban cards after a dataset version",
    tags=["job"],
)
def get_kanban_changes(request: HttpRequest, after: str | None = None) -> dict[str, object]:
    """Return changed Kanban cards after an opaque Job dataset version."""
    if after is None:
        raise HttpError(400, "after is required")
    try:
        changes = KanbanService.get_kanban_changes(after)
    except ValueError as exc:
        # The envelope's HttpError handler persists (following the cause chain).
        raise HttpError(400, str(exc)) from exc
    return {
        "success": True,
        "jobs": KanbanService.serialize_jobs_for_api(changes.jobs),
        "removed_job_ids": changes.removed_job_ids,
        "full_refresh_required": changes.full_refresh_required,
    }


@router.get(
    "/job/jobs/status-values/",
    auth=auth,
    operation_id="job_jobs_status_values_retrieve",
    response=FetchStatusValuesResponse,
    summary="Fetch kanban status values and tooltips",
    tags=["job"],
)
def job_jobs_status_values_retrieve(request: HttpRequest) -> dict[str, object]:
    """Return the kanban column choices and tooltips."""
    status_data = KanbanService.get_status_choices()
    return {"success": True, **status_data}


@router.get(
    "/job/jobs/advanced-search/",
    auth=auth,
    operation_id="job_jobs_advanced_search_retrieve",
    response=AdvancedSearchResponse,
    summary="Advanced job search",
    tags=["job"],
)
def job_jobs_advanced_search_retrieve(  # noqa: PLR0913, PLR0917 -- One argument per public search filter.
    request: HttpRequest,
    q: str = "",
    job_number: str = "",
    name: str = "",
    description: str = "",
    company_name: str = "",
    person_name: str = "",
    order_number: str = "",
    created_by: str = "",
    created_after: str = "",
    created_before: str = "",
    status: str = "",
    paid: str = "",
    rejected_flag: str = "",
    xero_invoice_params: str = "",
) -> dict[str, object]:
    """Search jobs across fields with optional universal weighted search."""
    filters: kanban_service.AdvancedSearchFilters = {
        "universal_search": q,
        "job_number": job_number,
        "name": name,
        "description": description,
        "company_name": company_name,
        "person_name": person_name,
        "order_number": order_number,
        "created_by": created_by,
        "created_after": created_after,
        "created_before": created_before,
        "paid": paid,
        "rejected_flag": rejected_flag,
        "xero_invoice_params": xero_invoice_params,
        "status": status.split(",") if status else [],
    }

    jobs = KanbanService.perform_advanced_search(filters)
    KanbanService.log_kanban_search_results(
        request=request,
        source="advanced",
        query=q,
        jobs=list(jobs),
        filters=dict(filters),
    )

    job_data = KanbanService.serialize_jobs_for_api(jobs)
    return {"success": True, "jobs": job_data, "total": len(job_data)}


@router.post(
    "/job/jobs/{uuid:job_id}/update-status/",
    auth=auth,
    operation_id="job_jobs_update_status_create",
    response=KanbanSuccessResponse,
    summary="Update a job's status from the kanban board",
    tags=["job"],
)
def job_jobs_update_status_create(
    request: HttpRequest, job_id: UUID, payload: JobStatusUpdateRequest
) -> dict[str, object]:
    """Move a job to a new status column."""
    try:
        KanbanService.update_job_status(job_id, payload.status, staff=_staff(request))
    except Job.DoesNotExist as exc:
        raise HttpError(404, "Job not found") from exc
    return {"success": True, "message": "Job status updated successfully"}


@router.post(
    "/job/jobs/{uuid:job_id}/reorder/",
    auth=auth,
    operation_id="job_jobs_reorder_create",
    response=KanbanSuccessResponse,
    summary="Reorder a job within or between kanban columns",
    tags=["job"],
)
def job_jobs_reorder_create(
    request: HttpRequest, job_id: UUID, payload: JobReorderRequest
) -> dict[str, object]:
    """Reorder a job against a visible anchor card."""
    # Enforce paired fields at the API boundary before invoking the service.
    if payload.anchor_job_id and not payload.placement:
        raise HttpError(400, "placement is required when anchor_job_id is supplied")
    if payload.placement and not payload.anchor_job_id:
        raise HttpError(400, "anchor_job_id is required when placement is supplied")
    try:
        KanbanService.reorder_job(
            job_id,
            anchor_job_id=str(payload.anchor_job_id) if payload.anchor_job_id else None,
            placement=payload.placement,
            new_status=payload.status,
            staff=_staff(request),
        )
    except Job.DoesNotExist as exc:
        raise HttpError(404, "Job not found") from exc
    except ValueError as exc:
        logger.warning("Invalid reorder request for job %s: %s", job_id, exc)
        raise HttpError(400, str(exc)) from exc
    return {"success": True, "message": "Job reordered successfully"}


@router.post(
    "/job/job/{uuid:job_id}/assignment",
    auth=auth,
    operation_id="job_job_assignment_create",
    response={200: AssignJobResponse, 400: AssignJobResponse},
    summary="Assign a staff member to a job",
    tags=["job"],
)
def job_job_assignment_create(
    request: HttpRequest, job_id: UUID, payload: AssignJobRequest
) -> Status[dict[str, object]]:
    """Assign staff to a job (kanban card avatars)."""
    success, error = job_service.assign_staff_to_job(job_id, payload.staff_id)
    if not success:
        logger.warning(
            "Staff assignment failed: job=%s staff=%s error=%s", job_id, payload.staff_id, error
        )
        return Status(400, {"success": False, "error": error})
    return Status(200, {"success": True, "message": "Job assigned to staff successfully."})


@router.delete(
    "/job/job/{uuid:job_id}/assignment/{uuid:staff_id}",
    auth=auth,
    operation_id="job_job_assignment_destroy",
    response={200: AssignJobResponse, 400: AssignJobResponse},
    summary="Remove a staff member from a job",
    tags=["job"],
)
def job_job_assignment_destroy(
    request: HttpRequest, job_id: UUID, staff_id: UUID
) -> Status[dict[str, object]]:
    """Remove an assigned staff member from a job."""
    success, error = job_service.remove_staff_from_job(job_id, staff_id)
    if not success:
        return Status(400, {"success": False, "error": error})
    return Status(200, {"success": True, "message": "Staff removed from job successfully."})


# ── Job files ────────────────────────────────────────────────────────────


def _get_job_file_or_404(job_id: UUID, file_id: UUID, *, active_only: bool = True) -> JobFile:
    job = _get_job_or_404(job_id)
    filters: dict[str, object] = {"id": file_id, "job": job}
    if active_only:
        filters["status"] = "active"
    return get_object_or_404(JobFile, **filters)


@router.get(
    "/job/jobs/{uuid:job_id}/files/",
    auth=auth,
    operation_id="listJobFiles",
    response=list[JobFileOut],
    summary="List all active files for a job",
    tags=["Job Files"],
)
def list_job_files(request: HttpRequest, job_id: UUID) -> list[job_service.JobFileData]:
    """List the job's active files."""
    job = _get_job_or_404(job_id)
    files = JobFile.objects.filter(job=job, status="active").select_related("job")
    return [job_service.job_file_data(job_file) for job_file in files]


def _enqueue_thumbnail(job: Job, job_file: JobFile, request: HttpRequest) -> None:
    """Enqueue thumbnail generation; persist (not fail) on broker errors."""
    try:
        create_job_file_thumbnail_task.delay(str(job_file.id))
    except Exception as thumb_exc:
        logger.exception("Could not enqueue thumbnail generation for file %s", job_file.id)
        persist_app_error(
            thumb_exc,
            AppErrorContext(
                job_id=str(job.id),
                user_id=str(_staff(request).id),
                additional_context={"file_id": str(job_file.id)},
            ),
        )


@router.post(
    "/job/jobs/{uuid:job_id}/files/",
    auth=office_auth,
    operation_id="uploadJobFiles",
    response={
        201: JobFileUploadSuccessResponse,
        207: JobFileUploadPartialResponse,
        400: JobFileUploadPartialResponse,
    },
    summary="Upload files to a job",
    tags=["Job Files"],
)
def upload_job_files(
    request: HttpRequest,
    job_id: UUID,
    files: NinjaFile[list[UploadedFile]],
    print_on_jobsheet: Form[bool] = True,
) -> Status[dict[str, object]]:
    """Upload one or more files into the job's folder (office staff only)."""
    job = _get_job_or_404(job_id)

    uploaded: list[job_service.JobFileData] = []
    errors: list[str] = []
    for file_obj in files:
        try:
            job_file = file_service.save_uploaded_job_file(job, file_obj, print_on_jobsheet)
        except Exception as exc:
            logger.exception("Error saving file %s", file_obj.name)
            persist_app_error(
                exc,
                AppErrorContext(
                    job_id=str(job.id),
                    user_id=str(_staff(request).id),
                    additional_context={"filename": file_obj.name},
                ),
            )
            errors.append(f"Failed to upload {file_obj.name}: {exc!s}")
            continue
        uploaded.append(job_service.job_file_data(job_file))
        # Generate thumbnails asynchronously so uploads are not blocked by
        # image processing.
        if (file_obj.content_type or "").startswith("image/"):
            _enqueue_thumbnail(job, job_file, request)

    if errors:
        return Status(
            207 if uploaded else 400,
            {
                "status": "partial_success" if uploaded else "error",
                "uploaded": uploaded,
                "errors": errors,
            },
        )
    return Status(
        201,
        {"status": "success", "uploaded": uploaded, "message": "Files uploaded successfully"},
    )


@router.get(
    "/job/jobs/{uuid:job_id}/files/{uuid:file_id}/",
    auth=auth,
    operation_id="getJobFile",
    summary="Download/view a specific job file",
    tags=["Job Files"],
)
def get_job_file(request: HttpRequest, job_id: UUID, file_id: UUID) -> HttpResponseBase:
    """Serve file content for inline download or viewing."""
    job_file = _get_job_file_or_404(job_id, file_id)
    full_path = file_service.job_file_full_path(job_file)

    if not full_path.exists():
        raise Http404("File not found on disk")

    response = FileResponse(full_path.open("rb"))
    content_type, _ = mimetypes.guess_type(full_path)
    if content_type:
        response["Content-Type"] = content_type
    response["Content-Disposition"] = f'inline; filename="{job_file.filename}"'
    return response


@router.put(
    "/job/jobs/{uuid:job_id}/files/{uuid:file_id}/",
    auth=office_auth,
    operation_id="updateJobFile",
    response=JobFileUpdateSuccessResponse,
    summary="Update job file metadata",
    tags=["Job Files"],
)
def update_job_file(
    request: HttpRequest, job_id: UUID, file_id: UUID, payload: JobFileUpdateRequest
) -> dict[str, object]:
    """Update print_on_jobsheet and/or rename the file (office staff only)."""
    job_file = _get_job_file_or_404(job_id, file_id)
    provided = payload.model_fields_set
    try:
        job_file = file_service.update_job_file(
            job_file,
            print_on_jobsheet=(
                payload.print_on_jobsheet if "print_on_jobsheet" in provided else None
            ),
            filename=payload.filename if "filename" in provided else None,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    logger.info("Updated file %s (job %s)", file_id, job_id)
    return {
        "status": "success",
        "message": "File updated successfully",
        "print_on_jobsheet": job_file.print_on_jobsheet,
        "filename": job_file.filename,
    }


@router.delete(
    "/job/jobs/{uuid:job_id}/files/{uuid:file_id}/",
    auth=office_auth,
    operation_id="deleteJobFile",
    response={204: None},
    summary="Delete a job file",
    tags=["Job Files"],
)
def delete_job_file(request: HttpRequest, job_id: UUID, file_id: UUID) -> Status[None]:
    """Delete a job file from disk and the database (office staff only)."""
    job_file = _get_job_file_or_404(job_id, file_id, active_only=False)
    file_service.delete_job_file(job_file)
    logger.info("Deleted file %s (job %s)", file_id, job_id)
    return Status(204, None)


@router.get(
    "/job/jobs/{uuid:job_id}/files/{uuid:file_id}/thumbnail/",
    auth=auth,
    operation_id="getJobFileThumbnail",
    summary="Get JPEG thumbnail for a job file",
    tags=["Job Files"],
)
def get_job_file_thumbnail(request: HttpRequest, job_id: UUID, file_id: UUID) -> HttpResponseBase:
    """Serve the JPEG thumbnail for a job file (images only)."""
    job_file = _get_job_file_or_404(job_id, file_id)
    thumb_path = job_file.thumbnail_path

    if not thumb_path or not Path(thumb_path).exists():
        raise Http404("Thumbnail not found")

    return FileResponse(Path(thumb_path).open("rb"), content_type="image/jpeg")


# ── Workshop PDF and delivery docket ─────────────────────────────────────


@router.get(
    "/job/jobs/{uuid:job_id}/workshop-pdf/",
    auth=auth,
    operation_id="job_jobs_workshop_pdf_retrieve",
    summary="Generate the workshop PDF for printing",
    tags=["job"],
)
def job_jobs_workshop_pdf_retrieve(request: HttpRequest, job_id: UUID) -> HttpResponseBase:
    """Generate and return the workshop PDF (inline, for direct printing)."""
    job = _get_job_or_404(job_id)
    pdf_buffer = create_workshop_pdf(job)
    response = FileResponse(
        pdf_buffer,
        as_attachment=False,
        filename=f"workshop_{job.job_number}.pdf",
        content_type="application/pdf",
    )
    response["Content-Disposition"] = f'inline; filename="workshop_{job.job_number}.pdf"'
    return response


@router.get(
    "/job/jobs/{uuid:job_id}/delivery-docket/",
    auth=office_auth,
    operation_id="generateDeliveryDocketRest",
    summary="Generate a delivery docket PDF and save it as a JobFile",
    tags=["job"],
)
def generate_delivery_docket_rest(request: HttpRequest, job_id: UUID) -> HttpResponseBase:
    """Generate, persist, and return a delivery docket PDF (office staff only)."""
    job = _get_job_or_404(job_id)
    pdf_buffer, job_file = generate_delivery_docket(job, staff=_staff(request))
    response = FileResponse(
        pdf_buffer,
        as_attachment=False,
        filename=job_file.filename,
        content_type="application/pdf",
    )
    # Inline disposition opens the file in the browser for printing.
    response["Content-Disposition"] = f'inline; filename="{job_file.filename}"'
    return response


# ── Month-end ────────────────────────────────────────────────────────────


def _month_end_job_payload(item: month_end_service.SpecialJobData) -> dict[str, object]:
    job = item["job"]
    return {
        "job_id": job.id,
        "job_number": job.job_number,
        "job_name": job.name,
        "company_name": job.company.name if job.company else "",
        "history": [
            {
                "date": timezone.localdate(entry["date"]),
                "total_hours": float(entry["total_hours"]),
                "total_dollars": float(entry["total_dollars"]),
            }
            for entry in item["history"]
        ],
        "total_hours": float(item["total_hours"]),
        "total_dollars": float(item["total_dollars"]),
    }


def _month_end_stock_payload(stock: month_end_service.StockJobData) -> dict[str, object]:
    job = stock["job"]
    return {
        "job_id": job.id,
        "job_number": job.job_number,
        "job_name": job.name,
        "history": [
            {
                "date": timezone.localdate(entry["date"]),
                "material_line_count": entry["material_line_count"],
                "material_cost": float(entry["material_cost"]),
            }
            for entry in stock["history"]
        ],
    }


@router.get(
    "/job/month-end/",
    auth=office_auth,
    operation_id="job_month_end_retrieve",
    response=MonthEndGetResponse,
    summary="Month-end special jobs and stock data",
    tags=["job"],
)
def job_month_end_retrieve(request: HttpRequest) -> dict[str, object]:
    """Return the special jobs and stock-job data for month-end review.

    Failures surface through the standard envelope handlers (ADR 0038).
    """
    special_jobs = month_end_service.get_special_jobs_data()
    return {
        "jobs": [_month_end_job_payload(item) for item in special_jobs],
        "stock_job": _month_end_stock_payload(month_end_service.get_stock_job_data()),
    }


@router.post(
    "/job/month-end/",
    auth=office_auth,
    operation_id="job_month_end_create",
    response=MonthEndPostResponse,
    summary="Runs month-end operation based on given processed ids",
    tags=["job"],
)
def job_month_end_create(request: HttpRequest, payload: MonthEndPostRequest) -> dict[str, object]:
    """Roll a new empty actual cost set for each selected job (office staff only)."""
    processed, errors = month_end_service.process_jobs(payload.job_ids, _staff(request))
    return {"processed": [job.id for job in processed], "errors": errors}
