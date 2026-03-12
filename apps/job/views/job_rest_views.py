"""
Job REST Views

REST views for the Job module following clean code principles:
- SRP (Single Responsibility Principle)
- Early return and guard clauses
- Delegation to service layer
- Views as orchestrators only
"""

import json
import logging
from typing import Any, Dict
from uuid import UUID

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.job.models import Job, JobDeltaRejection
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.job_serializer import (
    CompanyDefaultsJobDetailSerializer,
    JobBasicInformationResponseSerializer,
    JobCostSummaryResponseSerializer,
    JobCreateResponseSerializer,
    JobCreateSerializer,
    JobDeleteResponseSerializer,
    JobDeltaEnvelopeSerializer,
    JobDeltaRejectionListResponseSerializer,
    JobDetailResponseSerializer,
    JobEventCreateResponseSerializer,
    JobEventCreateSerializer,
    JobEventsResponseSerializer,
    JobHeaderResponseSerializer,
    JobInvoicesResponseSerializer,
    JobQuoteAcceptanceSerializer,
    JobRestErrorResponseSerializer,
    JobStatusChoicesResponseSerializer,
    JobSummaryResponseSerializer,
    JobTimelineResponseSerializer,
    JobUndoSerializer,
    QuoteSerializer,
    WeeklyMetricsSerializer,
)
from apps.job.services.job_rest_service import DeltaValidationError, JobRestService
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_and_raise
from apps.workflow.utils import parse_pagination_params

logger = logging.getLogger(__name__)


class BaseJobRestView(APIView):
    """
    Base view for Job REST operations.
    Implements common functionality like JSON parsing and error handling.
    Inherits from APIView for JWT authentication support.
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOfficeStaff()]

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        """Remove manual authentication check - let DRF handle it."""
        return super().dispatch(request, *args, **kwargs)

    def parse_json_body(self, request) -> Dict[str, Any]:
        """
        Parse the JSON body of the request.
        Apply early return in case of error.
        """
        if not request.body:
            raise ValueError("Request body is empty")

        try:
            return json.loads(request.body)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")

    def handle_service_error(self, error: Exception) -> Response:
        """
        Centralise service layer error handling with error persistence.
        """
        try:
            # Persist error for debugging
            persist_and_raise(error)
        except AlreadyLoggedException as logged_exc:
            logger.error(
                f"[JOB-REST-VIEW] Handled and persisted error {str(error)} "
                f"(error_id={logged_exc.app_error_id})"
            )
        except Exception as persist_error:
            logger.error(f"Failed to persist error: {persist_error}")

        error_message = str(error)

        match type(error).__name__:
            case "ValueError":
                error_response = {"error": error_message}
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )
            case "PermissionError":
                error_response = {"error": error_message}
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(error_serializer.data, status=status.HTTP_403_FORBIDDEN)
            case "IntegrityError":
                # Handle database constraint violations (duplicates)
                error_response = {
                    "error": "Duplicate event prevented by database constraint"
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(error_serializer.data, status=status.HTTP_409_CONFLICT)
            case "NotFound" | "Http404":
                error_response = {"error": "Resource not found"}
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
            case "PreconditionFailed" | "DeltaValidationError":
                # ETag mismatch -> Optimistic concurrency conflict
                error_response = {
                    "error": "Precondition failed (ETag mismatch). Reload the job and retry."
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_412_PRECONDITION_FAILED
                )
            case _:
                logger.exception(f"Unhandled error: {error}")
                error_response = {"error": "Internal server error"}
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

    def check_request_debounce(
        self, request, operation_key: str, debounce_seconds: int = 2
    ) -> bool:
        """
        Check if request is within debounce period.

        Args:
            request: HTTP request
            operation_key: Unique key for the operation
            debounce_seconds: Seconds to debounce

        Returns:
            bool: True if should be blocked (within debounce period)
        """
        user_id = str(request.user.id) if request.user.is_authenticated else "anonymous"
        cache_key = f"debounce:{operation_key}:{user_id}"

        # Check if entry exists in cache
        if cache.get(cache_key):
            return True  # Block - within debounce period

        # Set cache entry
        cache.set(cache_key, True, debounce_seconds)
        return False  # Allow - outside debounce period

    # === Optimistic Concurrency (ETag) helpers ===
    def _normalize_etag(self, etag: str | None) -> str | None:
        """Normalize an ETag/If-Match/If-None-Match value for comparison."""
        if not etag:
            return None
        val = etag.strip()
        if val.startswith("W/"):
            val = val[2:].strip()
        if len(val) >= 2 and (
            (val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")
        ):
            val = val[1:-1]
        return val

    def _gen_job_etag(self, job: Job) -> str:
        """Generate a weak ETag for a Job based on its last update timestamp."""
        try:
            ts_ms = int(job.updated_at.timestamp() * 1000)
        except Exception:
            ts_ms = 0
        return f'W/"job:{job.id}:{ts_ms}"'

    def _get_if_match(self, request) -> str | None:
        """Extract normalized If-Match header value."""
        header = request.headers.get("If-Match") or request.META.get("HTTP_IF_MATCH")
        return self._normalize_etag(header) if header else None

    def _get_if_none_match(self, request) -> str | None:
        """Extract normalized If-None-Match header value."""
        header = request.headers.get("If-None-Match") or request.META.get(
            "HTTP_IF_NONE_MATCH"
        )
        return self._normalize_etag(header) if header else None

    def _precondition_required_response(self) -> Response:
        """Return 428 when If-Match is required but missing."""
        error_response = {"error": "Missing If-Match header (precondition required)"}
        error_serializer = JobRestErrorResponseSerializer(error_response)
        return Response(
            error_serializer.data,
            status=getattr(status, "HTTP_428_PRECONDITION_REQUIRED", 428),
        )

    def _set_etag(self, response: Response, etag: str) -> Response:
        if etag:
            response["ETag"] = etag
        return response


@method_decorator(csrf_exempt, name="dispatch")
class JobCreateRestView(BaseJobRestView):
    """
    REST view for Job creation.
    Single responsibility: orchestrate job creation.
    """

    serializer_class = JobCreateResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "POST":
            return JobCreateSerializer
        return JobCreateResponseSerializer

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for the request for OpenAPI compatibility"""
        serializer_class = self.get_serializer_class()
        return serializer_class(*args, **kwargs)

    @extend_schema(
        request=JobCreateSerializer,
        responses={
            201: JobCreateResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Create a new Job. Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
    )
    def post(self, request):
        """
        Create a new Job.

        Expected JSON:
        {
            "name": "Job Name",
            "client_id": "client-uuid",
            "description": "Optional description",
            "order_number": "Optional order number",
            "notes": "Optional notes",
            "contact_id": "optional-contact-uuid"
            "pricing_methodology": "Optional methodology (defaults to T&M)"
        }
        """
        try:
            data = self.parse_json_body(request)

            # Validate input data
            input_serializer = JobCreateSerializer(data=data)
            if not input_serializer.is_valid():
                error_response = {
                    "error": f"Validation failed: {input_serializer.errors}"
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            job = JobRestService.create_job(
                input_serializer.validated_data, request.user
            )

            response_data = {
                "success": True,
                "job_id": str(job.id),
                "job_number": job.job_number,
                "message": "Job created successfully",
            }

            response_serializer = JobCreateResponseSerializer(response_data)
            response = Response(
                response_serializer.data, status=status.HTTP_201_CREATED
            )
            try:
                etag = self._gen_job_etag(job)
                response["ETag"] = etag
            except Exception as e:
                logger.warning(f"Failed to set ETag for created job {job.id}: {e}")
            return response

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobDetailRestView(BaseJobRestView):
    """
    REST view for CRUD operations on a specific Job.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JobDetailResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "DELETE":
            return JobDeleteResponseSerializer
        return JobDetailResponseSerializer

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for the request for OpenAPI compatibility"""
        serializer_class = self.get_serializer_class()
        return serializer_class(*args, **kwargs)

    @extend_schema(
        responses={200: JobDetailResponseSerializer},
        description="Fetch complete job data including financial information. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
        operation_id="getFullJob",
    )
    def get(self, request, job_id):
        """
        Fetch complete Job data for editing.
        """
        try:
            # Conditional GET using ETag
            try:
                job_for_etag = Job.objects.only("id", "updated_at").get(id=job_id)
                current_etag = self._gen_job_etag(job_for_etag)
            except Job.DoesNotExist:
                current_etag = None

            if_none_match = self._get_if_none_match(request)
            if (
                if_none_match
                and current_etag
                and self._normalize_etag(current_etag) == if_none_match
            ):
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            job_data = JobRestService.get_job_for_edit(job_id, request)

            # The service returns already-serialized data, so return it directly
            response_data = {"success": True, "data": job_data}
            resp = Response(response_data, status=status.HTTP_200_OK)

            # Recompute ETag after read to ensure accuracy
            try:
                job_for_etag = Job.objects.only("id", "updated_at").get(id=job_id)
                current_etag = self._gen_job_etag(job_for_etag)
                resp = self._set_etag(resp, current_etag)
            except Job.DoesNotExist:
                pass

            return resp

        except Exception as e:
            return self.handle_service_error(e)

    @extend_schema(
        request=JobDeltaEnvelopeSerializer,
        responses={
            200: JobDetailResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Update Job data (autosave). Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
    )
    def put(self, request, job_id):
        """
        Update Job data (autosave).
        """
        try:
            data = self.parse_json_body(request)
            delta_serializer = JobDeltaEnvelopeSerializer(data=data)
            if not delta_serializer.is_valid():
                error_response = {
                    "error": f"Validation failed: {delta_serializer.errors}"
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )
            payload = delta_serializer.validated_data

            # Require If-Match for optimistic concurrency control
            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            # Update the job using the service layer with concurrency check
            try:
                updated_job = JobRestService.update_job(
                    job_id, payload, request.user, if_match=if_match
                )
            except DeltaValidationError as exc:
                change_id = payload.get("change_id")
                job_instance = Job.objects.filter(id=job_id).only("id").first()
                change_uuid = change_id if change_id else None
                already_recorded = (
                    JobDeltaRejection.objects.filter(
                        job=job_instance, change_id=change_uuid
                    ).exists()
                    if job_instance and change_uuid
                    else False
                )

                if not already_recorded:
                    staff_member = (
                        request.user if isinstance(request.user, Staff) else None
                    )
                    JobRestService._record_delta_rejection(
                        job=job_instance,
                        staff=staff_member,
                        reason=str(exc),
                        detail={
                            "server_checksum": getattr(exc, "server_checksum", None),
                            "current_values": getattr(exc, "current_values", {}),
                        },
                        envelope=payload,
                        change_id=str(change_id) if change_id else None,
                        checksum=payload.get("before_checksum"),
                        request_etag=payload.get("etag") or if_match,
                        request_ip=request.META.get("REMOTE_ADDR"),
                    )
                raise

            # Return complete job data for frontend reactivity
            job_data = JobRestService.get_job_for_edit(job_id, request)

            # The service returns already-serialized data, so wrap it properly
            response_data = {"success": True, "data": job_data}
            resp = Response(response_data, status=status.HTTP_200_OK)
            resp = self._set_etag(resp, self._gen_job_etag(updated_job))
            return resp

        except Exception as e:
            return self.handle_service_error(e)

    @extend_schema(
        request=JobDeltaEnvelopeSerializer,
        responses={
            200: JobDetailResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Partially update Job data. Only updates the fields provided in the request body. Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
    )
    def patch(self, request, job_id):
        """
        Partially update Job data.
        Only updates the fields provided in the request body.
        """
        try:
            data = self.parse_json_body(request)
            delta_serializer = JobDeltaEnvelopeSerializer(data=data)
            if not delta_serializer.is_valid():
                error_response = {
                    "error": f"Validation failed: {delta_serializer.errors}"
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )
            payload = delta_serializer.validated_data

            # Require If-Match for optimistic concurrency control
            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            # Update the job using the service layer (supports partial updates) with concurrency check
            try:
                updated_job = JobRestService.update_job(
                    job_id, payload, request.user, if_match=if_match
                )
            except DeltaValidationError as exc:
                change_id = payload.get("change_id")
                job_instance = Job.objects.filter(id=job_id).only("id").first()
                change_uuid = change_id if change_id else None
                already_recorded = (
                    JobDeltaRejection.objects.filter(
                        job=job_instance, change_id=change_uuid
                    ).exists()
                    if job_instance and change_uuid
                    else False
                )

                if not already_recorded:
                    staff_member = (
                        request.user if isinstance(request.user, Staff) else None
                    )
                    JobRestService._record_delta_rejection(
                        job=job_instance,
                        staff=staff_member,
                        reason=str(exc),
                        detail={
                            "server_checksum": getattr(exc, "server_checksum", None),
                            "current_values": getattr(exc, "current_values", {}),
                        },
                        envelope=payload,
                        change_id=str(change_id) if change_id else None,
                        checksum=payload.get("before_checksum"),
                        request_etag=payload.get("etag") or if_match,
                        request_ip=request.META.get("REMOTE_ADDR"),
                    )
                raise

            # Return complete job data for frontend reactivity
            job_data = JobRestService.get_job_for_edit(job_id, request)

            # The service returns already-serialized data, so wrap it properly
            response_data = {"success": True, "data": job_data}
            resp = Response(response_data, status=status.HTTP_200_OK)
            resp = self._set_etag(resp, self._gen_job_etag(updated_job))
            return resp

        except Exception as e:
            return self.handle_service_error(e)

    @extend_schema(
        responses={
            200: JobDeleteResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Delete a Job if permitted. Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
    )
    def delete(self, request, job_id):
        """
        Delete a Job if permitted.
        """
        try:
            # Require If-Match for optimistic concurrency control on delete
            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            result = JobRestService.delete_job(job_id, request.user, if_match=if_match)

            # Serialize the result properly
            response_serializer = JobDeleteResponseSerializer(result)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValueError as v:
            logger.error("Error deleting job: valid data found.")
            error = {"error": str(v)}
            return Response(
                JobRestErrorResponseSerializer(error).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobSummaryRestView(BaseJobRestView):
    """
    REST view for Job summary data (no cost lines or events).
    Returns the same response shape as JobDetailRestView but with
    cost_lines: [] and events: [] for lightweight fetching.
    """

    serializer_class = JobSummaryResponseSerializer

    @extend_schema(
        responses={
            200: JobSummaryResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch job summary with cost set totals but no individual cost lines or events.",
        tags=["Jobs"],
        operation_id="getJobSummary",
    )
    def get(self, request, job_id):
        try:
            # Conditional GET using ETag
            try:
                job_for_etag = Job.objects.only("id", "updated_at").get(id=job_id)
                current_etag = self._gen_job_etag(job_for_etag)
            except Job.DoesNotExist:
                current_etag = None

            if_none_match = self._get_if_none_match(request)
            if (
                if_none_match
                and current_etag
                and self._normalize_etag(current_etag) == if_none_match
            ):
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            job_data = JobRestService.get_job_summary(job_id, request)

            response_data = {"success": True, "data": job_data}
            resp = Response(response_data, status=status.HTTP_200_OK)

            try:
                job_for_etag = Job.objects.only("id", "updated_at").get(id=job_id)
                current_etag = self._gen_job_etag(job_for_etag)
                resp = self._set_etag(resp, current_etag)
            except Job.DoesNotExist:
                pass

            return resp

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobEventRestView(BaseJobRestView):
    """
    REST view for Job events.
    """

    serializer_class = JobEventCreateResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "POST":
            return JobEventCreateSerializer
        return JobEventCreateResponseSerializer

    @extend_schema(
        request=JobEventCreateSerializer,
        responses={
            201: JobEventCreateResponseSerializer,
            409: JobRestErrorResponseSerializer,
            400: JobRestErrorResponseSerializer,
            429: JobRestErrorResponseSerializer,
        },
        description="Add a manual event to the Job with duplicate prevention. Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
        operation_id="job_rest_jobs_events_create",
    )
    def post(self, request, job_id):
        """
        Add a manual event to the Job with duplicate prevention.

        Expected JSON:
        {
            "description": "Event description"
        }
        """
        try:
            # Debounce check - prevent rapid requests
            debounce_key = f"add_event:{job_id}"
            if self.check_request_debounce(request, debounce_key, debounce_seconds=2):
                logger.warning(
                    f"Request debounced for user {request.user.email} on job {job_id}"
                )
                error_response = {
                    "error": "Request too frequent. Please wait before adding another event."
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            data = self.parse_json_body(request)

            # Validate input data
            input_serializer = JobEventCreateSerializer(data=data)
            if not input_serializer.is_valid():
                error_response = {
                    "error": f"Validation failed: {input_serializer.errors}"
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            # Additional duplicate check via cache
            description = input_serializer.validated_data["description"].strip()
            duplicate_check_key = (
                f"event_duplicate:{job_id}:{request.user.id}:{hash(description)}"
            )

            if cache.get(duplicate_check_key):
                logger.warning(
                    f"Duplicate event prevented via cache for user {request.user.email} on job {job_id}"
                )
                error_response = {
                    "error": "Duplicate event detected. An identical event was recently created."
                }
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(error_serializer.data, status=status.HTTP_409_CONFLICT)

            # Require If-Match for optimistic concurrency control on event creation
            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            # Verify client ETag against current job version
            try:
                job_for_etag = Job.objects.only("id", "updated_at").get(id=job_id)
                current_etag_norm = self._normalize_etag(
                    self._gen_job_etag(job_for_etag)
                )
                if current_etag_norm != if_match:
                    error_response = {
                        "error": "Precondition failed (ETag mismatch). Reload the job and retry."
                    }
                    error_serializer = JobRestErrorResponseSerializer(error_response)
                    return Response(
                        error_serializer.data,
                        status=status.HTTP_412_PRECONDITION_FAILED,
                    )
            except Job.DoesNotExist:
                error_response = {"error": "Resource not found"}
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Create event via service
            result = JobRestService.add_job_event(job_id, description, request.user)

            # Set duplicate prevention cache (5 minutes)
            cache.set(duplicate_check_key, True, 300)

            # Return appropriate status based on whether duplicate was prevented
            response_serializer = JobEventCreateResponseSerializer(result)
            if result.get("duplicate_prevented"):
                resp = Response(
                    response_serializer.data, status=status.HTTP_409_CONFLICT
                )
            else:
                resp = Response(
                    response_serializer.data, status=status.HTTP_201_CREATED
                )
            # Set fresh ETag for job after mutation
            try:
                job = Job.objects.only("id", "updated_at").get(id=job_id)
                resp = self._set_etag(resp, self._gen_job_etag(job))
            except Job.DoesNotExist:
                pass
            return resp

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobQuoteAcceptRestView(BaseJobRestView):
    """
    REST view for accepting job quotes.
    """

    serializer_class = JobQuoteAcceptanceSerializer

    @extend_schema(
        responses={
            200: JobQuoteAcceptanceSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Accept a quote for the job. Sets the quote_acceptance_date to current datetime. Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
    )
    def post(self, request, job_id):
        """
        Accept a quote for the job.
        Sets the quote_acceptance_date to current datetime.
        """
        try:
            # Require If-Match for optimistic concurrency control
            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            result = JobRestService.accept_quote(
                job_id, request.user, if_match=if_match
            )

            # Create response with proper typing
            response_data = {
                "success": result["success"],
                "job_id": result["job_id"],
                "quote_acceptance_date": result["quote_acceptance_date"],
                "message": result["message"],
            }

            payload = JobQuoteAcceptanceSerializer(response_data).data

            resp = Response(payload, status=status.HTTP_200_OK)
            try:
                job = Job.objects.only("id", "updated_at").get(id=job_id)
                resp = self._set_etag(resp, self._gen_job_etag(job))
            except Job.DoesNotExist:
                pass
            return resp

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class WeeklyMetricsRestView(BaseJobRestView):
    """
    REST view for fetching weekly metrics.
    """

    serializer = WeeklyMetricsSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="week",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Month (1-12). Defaults to current month.",
            ),
        ],
        responses={200: WeeklyMetricsSerializer(many=True)},
        description="Fetch weekly metrics data for jobs with time entries in the specified week. Concurrency is controlled in this endpoint (E-tag/If-Match).",
        tags=["Jobs"],
    )
    def get(self, request):
        """
        Fetch weekly metrics data.
        """
        try:
            week_param = request.query_params.get("week")
            week_date = None
            if week_param:
                from django.utils.dateparse import parse_date

                week_date = parse_date(week_param)
                if not week_date:
                    error_response = {
                        "error": "Invalid week date format. Use YYYY-MM-DD"
                    }
                    error_serializer = JobRestErrorResponseSerializer(error_response)
                    return Response(
                        error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                    )

            logger.info(
                f"WeeklyMetricsRestView: week_param={week_param}, week_date={week_date}"
            )

            metrics_data = JobRestService.get_weekly_metrics(week_date)

            serializer = WeeklyMetricsSerializer(metrics_data, many=True)

            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching weekly metrics: {e}")
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobHeaderRestView(BaseJobRestView):
    """
    REST view for Job header information.
    Returns essential job data for fast initial loading.
    """

    serializer_class = JobHeaderResponseSerializer

    @extend_schema(
        responses={
            200: JobHeaderResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch essential job header information for fast loading. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch essential job header data for fast initial loading.
        """
        try:
            # Query fields derived from JOB_DIRECT_FIELDS, plus id and client/contact for joins
            query_fields = [
                "id",
                "updated_at",
                "client_id",
                "contact_id",
            ] + Job.JOB_DIRECT_FIELDS
            job = (
                Job.objects.select_related("client", "contact")
                .only(*query_fields)
                .get(id=job_id)
            )

            current_etag = self._gen_job_etag(job)

            # Conditional GET using ETag
            if_none_match = self._get_if_none_match(request)
            if if_none_match and self._normalize_etag(current_etag) == if_none_match:
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            # Let the serializer handle field serialization
            serializer = JobHeaderResponseSerializer(job)
            resp = Response(serializer.data, status=status.HTTP_200_OK)
            resp = self._set_etag(resp, current_etag)
            return resp

        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")
        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobInvoicesRestView(BaseJobRestView):
    """
    REST view for Job invoices.
    Returns list of invoices for a job.
    """

    serializer_class = JobInvoicesResponseSerializer

    @extend_schema(
        responses={
            200: JobInvoicesResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch job invoices list. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch job invoices.
        """
        try:
            # ETag for conditional GET
            job = Job.objects.only("id", "updated_at").get(id=job_id)
            current_etag = self._gen_job_etag(job)
            inm = self._get_if_none_match(request)
            if inm and self._normalize_etag(current_etag) == inm:
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            invoices = JobRestService.get_job_invoices(job_id)

            serializer = JobInvoicesResponseSerializer({"invoices": invoices})
            resp = Response(serializer.data, status=status.HTTP_200_OK)
            return self._set_etag(resp, current_etag)

        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")
        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobQuoteRestView(BaseJobRestView):
    """
    REST view for Job quotes.
    Returns the xero quote for a job.
    """

    serializer_class = QuoteSerializer

    @extend_schema(
        responses={
            200: QuoteSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch job quote. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch job quote.
        """
        try:
            # ETag for conditional GET
            job = Job.objects.only("id", "updated_at").get(id=job_id)
            current_etag = self._gen_job_etag(job)
            inm = self._get_if_none_match(request)
            if inm and self._normalize_etag(current_etag) == inm:
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            quote = JobRestService.get_job_quote(job_id)

            resp = Response(quote, status=status.HTTP_200_OK)
            return self._set_etag(resp, current_etag)

        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")
        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobCostSummaryRestView(BaseJobRestView):
    """
    REST view for Job cost summary.
    Returns cost summary across all cost sets.
    """

    serializer_class = JobCostSummaryResponseSerializer

    @extend_schema(
        responses={
            200: JobCostSummaryResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch job cost summary across all cost sets. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch job cost summary in frontend-expected format.
        """
        try:
            # ETag for conditional GET
            job = Job.objects.only("id", "updated_at").get(id=job_id)
            current_etag = self._gen_job_etag(job)
            inm = self._get_if_none_match(request)
            if inm and self._normalize_etag(current_etag) == inm:
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            # Get summaries from all cost sets
            estimate = job.get_latest("estimate")
            quote = job.get_latest("quote")
            actual = job.get_latest("actual")

            def calculate_profit_margin(cost_set):
                """Calculate profit margin as (rev - cost) / cost * 100"""
                if not cost_set or not cost_set.summary:
                    return None
                summary = cost_set.summary
                cost = summary.get("cost", 0)
                rev = summary.get("rev", 0)
                if cost and cost > 0:
                    return ((rev - cost) / cost) * 100
                return 0

            # Build frontend-expected summary data with profitMargin
            summary_data = {
                "estimate": (
                    {
                        "cost": (
                            estimate.summary.get("cost", 0)
                            if estimate and estimate.summary
                            else 0
                        ),
                        "rev": (
                            estimate.summary.get("rev", 0)
                            if estimate and estimate.summary
                            else 0
                        ),
                        "hours": (
                            estimate.summary.get("hours", 0)
                            if estimate and estimate.summary
                            else 0
                        ),
                        "profitMargin": calculate_profit_margin(estimate),
                    }
                    if estimate and estimate.summary
                    else None
                ),
                "quote": (
                    {
                        "cost": (
                            quote.summary.get("cost", 0)
                            if quote and quote.summary
                            else 0
                        ),
                        "rev": (
                            quote.summary.get("rev", 0)
                            if quote and quote.summary
                            else 0
                        ),
                        "hours": (
                            quote.summary.get("hours", 0)
                            if quote and quote.summary
                            else 0
                        ),
                        "profitMargin": calculate_profit_margin(quote),
                    }
                    if quote and quote.summary
                    else None
                ),
                "actual": (
                    {
                        "cost": (
                            actual.summary.get("cost", 0)
                            if actual and actual.summary
                            else 0
                        ),
                        "rev": (
                            actual.summary.get("rev", 0)
                            if actual and actual.summary
                            else 0
                        ),
                        "hours": (
                            actual.summary.get("hours", 0)
                            if actual and actual.summary
                            else 0
                        ),
                        "profitMargin": calculate_profit_margin(actual),
                    }
                    if actual and actual.summary
                    else None
                ),
            }

            serializer = JobCostSummaryResponseSerializer(summary_data)
            resp = Response(serializer.data, status=status.HTTP_200_OK)
            return self._set_etag(resp, current_etag)

        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")
        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobStatusChoicesRestView(BaseJobRestView):
    """
    REST view for Job status choices.
    Returns available status choices for jobs.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JobStatusChoicesResponseSerializer

    @extend_schema(
        responses={
            200: JobStatusChoicesResponseSerializer,
        },
        description="Fetch job status choices. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request):
        """
        Fetch job status choices.
        """
        try:
            from apps.job.models.job import Job

            # Get status choices from model
            status_choices = dict(Job.STATUS_CHOICES)

            response_data = {"statuses": status_choices}
            serializer = JobStatusChoicesResponseSerializer(response_data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobEventListRestView(BaseJobRestView):
    """
    REST view for Job events list.
    Returns list of events for a job.
    """

    serializer_class = JobEventsResponseSerializer

    @extend_schema(
        responses={
            200: JobEventsResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch job events list. Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch job events.
        """
        try:
            job = Job.objects.get(id=job_id)
            events = job.events.all().order_by("-timestamp")

            serializer = JobEventsResponseSerializer({"events": events})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")
        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobDeltaRejectionListRestView(BaseJobRestView):
    """REST view that returns delta rejections for a specific job."""

    serializer_class = JobDeltaRejectionListResponseSerializer

    @extend_schema(
        operation_id="job_rest_job_delta_rejections_list",
        responses={
            200: JobDeltaRejectionListResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Maximum number of records to return (default 50, max 200).",
            ),
            OpenApiParameter(
                name="offset",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Offset for pagination (default 0).",
            ),
        ],
        description="Fetch delta rejections recorded for this job.",
        tags=["Jobs"],
    )
    def get(self, request, job_id: UUID):
        try:
            job = get_object_or_404(Job.objects.only("id"), id=job_id)
        except Exception:
            raise ValueError(f"Job with id {job_id} not found")

        try:
            limit, offset = parse_pagination_params(request)
        except ValueError:
            return self.handle_service_error(
                ValueError("Invalid pagination parameters")
            )

        payload = JobRestService.list_job_delta_rejections(
            job_id=str(job.id), limit=limit, offset=offset
        )
        serializer = JobDeltaRejectionListResponseSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class JobDeltaRejectionAdminRestView(BaseJobRestView):
    """Global listing of delta rejections for admin/monitoring usage."""

    serializer_class = JobDeltaRejectionListResponseSerializer

    @extend_schema(
        operation_id="job_rest_jobs_delta_rejections_admin_list",
        responses={
            200: JobDeltaRejectionListResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        parameters=[
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Maximum number of records to return (default 50, max 200).",
            ),
            OpenApiParameter(
                name="offset",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Offset for pagination (default 0).",
            ),
            OpenApiParameter(
                name="job_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional job UUID filter.",
            ),
        ],
        description="Fetch rejected job delta envelopes (global admin view).",
        tags=["Jobs"],
    )
    def get(self, request):
        try:
            limit = int(request.query_params.get("limit", "50"))
            offset = int(request.query_params.get("offset", "0"))
        except (TypeError, ValueError):
            return self.handle_service_error(
                ValueError("Invalid pagination parameters")
            )

        job_filter = request.query_params.get("job_id")
        job_id: str | None = None
        if job_filter:
            try:
                job_id = str(UUID(str(job_filter)))
            except ValueError:
                return self.handle_service_error(ValueError("Invalid job_id parameter"))

        payload = JobRestService.list_job_delta_rejections(
            job_id=job_id, limit=limit, offset=offset
        )
        serializer = JobDeltaRejectionListResponseSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class JobTimelineRestView(BaseJobRestView):
    """
    REST view for unified Job timeline.
    Returns combined JobEvents and CostLine data in chronological order.
    """

    serializer_class = JobTimelineResponseSerializer

    @extend_schema(
        responses={
            200: JobTimelineResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch unified job timeline (events + cost lines)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch unified job timeline combining events and cost line entries.
        """
        try:
            timeline = JobRestService.get_job_timeline(job_id)
            serializer = JobTimelineResponseSerializer({"timeline": timeline})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ValueError as e:
            return self.handle_service_error(e)
        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobUndoChangeRestView(BaseJobRestView):
    """Undo a previously applied job delta."""

    serializer_class = JobUndoSerializer

    @extend_schema(
        request=JobUndoSerializer,
        responses={
            200: JobDetailResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Undo a previously applied job delta (requires delta envelope undo support).",
        tags=["Jobs"],
    )
    def post(self, request, job_id):
        try:
            data = self.parse_json_body(request)
            serializer = JobUndoSerializer(data=data)
            if not serializer.is_valid():
                error_response = {"error": f"Validation failed: {serializer.errors}"}
                error_serializer = JobRestErrorResponseSerializer(error_response)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            undo_change_id = serializer.validated_data.get("undo_change_id")
            change_id = serializer.validated_data["change_id"]

            updated_job = JobRestService.undo_job_change(
                job_id,
                change_id,
                request.user,
                if_match=if_match,
                undo_change_id=undo_change_id,
            )

            job_data = JobRestService.get_job_for_edit(job_id, request)
            response_data = {"success": True, "data": job_data}
            resp = Response(response_data, status=status.HTTP_200_OK)
            resp = self._set_etag(resp, self._gen_job_etag(updated_job))
            return resp

        except Exception as e:
            return self.handle_service_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobBasicInformationRestView(BaseJobRestView):
    """
    REST view for Job basic information.
    Returns description, delivery date, order number and internal notes.
    """

    serializer_class = JobBasicInformationResponseSerializer

    @extend_schema(
        responses={
            200: JobBasicInformationResponseSerializer,
            400: JobRestErrorResponseSerializer,
        },
        description="Fetch job basic information (description, delivery date, order number, notes). Concurrency is controlled in this endpoint (E-tag/If-Match)",
        tags=["Jobs"],
    )
    def get(self, request, job_id):
        """
        Fetch job basic information.
        """
        try:
            # Conditional GET using ETag based on Job.updated_at
            try:
                job = Job.objects.only("id", "updated_at").get(id=job_id)
                current_etag = self._gen_job_etag(job)
            except Job.DoesNotExist:
                raise ValueError(f"Job with id {job_id} not found")

            if_none_match = self._get_if_none_match(request)
            if if_none_match and self._normalize_etag(current_etag) == if_none_match:
                resp = Response(status=status.HTTP_304_NOT_MODIFIED)
                return self._set_etag(resp, current_etag)

            basic_info = JobRestService.get_job_basic_information(job_id)

            serializer = JobBasicInformationResponseSerializer(basic_info)
            resp = Response(serializer.data, status=status.HTTP_200_OK)
            return self._set_etag(resp, current_etag)

        except Exception as e:
            return self.handle_service_error(e)


@extend_schema(
    responses={200: CompanyDefaultsJobDetailSerializer},
    description="Fetch company default settings.",
    tags=["Jobs"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_company_defaults_api(request):
    """
    API endpoint to fetch company default settings.
    Retrieves the singleton CompanyDefaults instance.
    """
    defaults = CompanyDefaults.get_solo()
    return JsonResponse(
        {
            "materials_markup": float(defaults.materials_markup),
            "time_markup": float(defaults.time_markup),
            "charge_out_rate": float(defaults.charge_out_rate),
            "wage_rate": float(defaults.wage_rate),
        }
    )
