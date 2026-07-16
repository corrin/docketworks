"""
Company REST Views

REST views for the Company module following clean code principles:
- SRP (Single Responsibility Principle)
- Early return and guard clauses
- Delegation to service layer
- Views as orchestrators only
"""

import logging
from typing import Any, Dict
from uuid import UUID

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.company.models import Company, ContactMethod
from apps.company.serializers import (
    CompanyCreateResponseSerializer,
    CompanyCreateSerializer,
    CompanyDetailResponseSerializer,
    CompanyDuplicateErrorResponseSerializer,
    CompanyErrorResponseSerializer,
    CompanyJobsResponseSerializer,
    CompanyListResponseSerializer,
    CompanyNameOnlySerializer,
    CompanySearchResponseSerializer,
    CompanyUpdateResponseSerializer,
    CompanyUpdateSerializer,
    JobPersonResponseSerializer,
    JobPersonUpdateSerializer,
)
from apps.company.services.company_rest_service import CompanyRestService
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


def _build_server_error_response(
    *,
    message: str,
    exc: Exception,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
) -> Response:
    """Serialize an error response while ensuring exceptions persist only once."""
    if isinstance(exc, AlreadyLoggedException):
        root_exc = exc.original
        error_id = exc.app_error_id
    else:
        root_exc = exc
        app_error = persist_app_error(exc)
        error_id = getattr(app_error, "id", None)

    logger.error("%s: %s", message, root_exc)

    payload: Dict[str, Any] = {"error": message, "details": str(root_exc)}
    if error_id:
        payload["error_id"] = str(error_id)

    serializer = CompanyErrorResponseSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    return Response(serializer.data, status=status_code)


@extend_schema_view(
    get=extend_schema(
        summary="List all companies",
        description="Returns a list of all companies with basic information (id and name) for dropdowns and search.",
        responses={
            200: CompanyNameOnlySerializer(many=True),
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    )
)
class CompanyListAllRestView(APIView):
    """
    REST view for listing all companies.
    Used by dropdowns and advanced search.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanyListResponseSerializer

    def get(self, request: Request) -> Response:
        """
        Lists all companies (only id and name) for fast dropdowns.
        """
        try:
            companies_data = CompanyRestService.get_all_companies()
            return Response(companies_data)
        except Exception as exc:
            return _build_server_error_response(
                message="Error fetching all companies", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Search companies",
        parameters=[
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search query (case-insensitive substring match). If empty, returns all companies.",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="page",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page number (default 1)",
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name="page_size",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Results per page (default 50)",
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name="sort_by",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Field to sort by (default 'name')",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="sort_dir",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort direction: 'asc' or 'desc' (default 'asc')",
                type=OpenApiTypes.STR,
            ),
        ],
        responses={
            200: CompanySearchResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    )
)
class CompanySearchRestView(APIView):
    """
    REST view for company search with pagination and sorting.
    Returns all companies when no search query provided.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanySearchResponseSerializer

    def get(self, request: Request) -> Response:
        """
        Lists/searches companies with pagination and sorting.
        """
        try:
            query = (request.GET.get("q") or "").strip()

            # Parse pagination params
            try:
                page = max(1, int(request.GET.get("page", 1)))
            except ValueError:
                page = 1
            try:
                page_size = int(request.GET.get("page_size", 50))
            except ValueError:
                page_size = 50
            page_size = max(1, page_size)

            # Parse sorting params
            sort_by = request.GET.get("sort_by", "name")
            sort_dir = request.GET.get("sort_dir", "asc")

            # Get paginated results
            result = CompanyRestService.list_companies(
                query=query if len(query) >= 3 else None,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_dir=sort_dir,
            )

            serializer = CompanySearchResponseSerializer(data=result)
            serializer.is_valid(raise_exception=True)
            CompanyRestService.log_company_search_results(
                request=request,
                source="company_search",
                query=query,
                companies=result["results"],
                total_count=result["count"],
            )
            return Response(serializer.data)

        except Exception as exc:
            return _build_server_error_response(
                message="Error searching companies", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get company details",
        description="Retrieve detailed information for a specific company.",
        parameters=[
            OpenApiParameter(
                name="company_id",
                location=OpenApiParameter.PATH,
                description="UUID of the company",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        responses={
            200: CompanyDetailResponseSerializer,
            404: CompanyErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    )
)
class CompanyRetrieveRestView(APIView):
    """
    REST view for retrieving a specific company by ID.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanyDetailResponseSerializer

    def get(self, request: Request, company_id: str) -> Response:
        """
        Retrieves detailed information for a specific company.
        """
        try:
            company_data = CompanyRestService.get_company_by_id(company_id)
            return Response(company_data)
        except ValueError as e:
            error_serializer = CompanyErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return _build_server_error_response(
                message="Error retrieving company", exc=exc
            )


@extend_schema_view(
    put=extend_schema(
        summary="Update company",
        description="Update an existing company's information.",
        parameters=[
            OpenApiParameter(
                name="company_id",
                location=OpenApiParameter.PATH,
                description="UUID of the company",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        request=CompanyUpdateSerializer,
        responses={
            200: CompanyUpdateResponseSerializer,
            400: CompanyErrorResponseSerializer,
            404: CompanyErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    ),
    patch=extend_schema(
        summary="Partially update company",
        description="Partially update an existing company's information.",
        parameters=[
            OpenApiParameter(
                name="company_id",
                location=OpenApiParameter.PATH,
                description="UUID of the company",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        request=CompanyUpdateSerializer,
        responses={
            200: CompanyUpdateResponseSerializer,
            400: CompanyErrorResponseSerializer,
            404: CompanyErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    ),
)
class CompanyUpdateRestView(APIView):
    """
    REST view for updating company information.
    Supports both PUT (full update) and PATCH (partial update).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanyUpdateResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method in ["PUT", "PATCH"]:
            return CompanyUpdateSerializer
        return CompanyUpdateResponseSerializer

    def put(self, request: Request, company_id: str) -> Response:
        """
        Full update of company information.
        """
        return self._update_company(request, company_id, partial=False)

    def patch(self, request: Request, company_id: str) -> Response:
        """
        Partial update of company information.
        """
        return self._update_company(request, company_id, partial=True)

    def _update_company(
        self, request: Request, company_id: str, partial: bool = True
    ) -> Response:
        """
        Common method for handling company updates.
        """
        try:
            # Validate input data
            input_serializer = CompanyUpdateSerializer(
                data=request.data, partial=partial
            )
            if not input_serializer.is_valid():
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": f"Invalid input data: {input_serializer.errors}"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            validated_data = input_serializer.validated_data
            updated_company = CompanyRestService.update_company(
                company_id, validated_data
            )

            # Format response using the service method
            company_data = CompanyRestService._format_company_detail(updated_company)
            response_data = {
                "success": True,
                "company": company_data,
                "message": f'Company "{updated_company.name}" updated successfully',
            }

            response_serializer = CompanyUpdateResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data)

        except ValueError as e:
            # Handle not found and validation errors
            if "not found" in str(e).lower():
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": str(e)}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
            else:
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": str(e)}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as exc:
            return _build_server_error_response(
                message="Error updating company", exc=exc
            )


@extend_schema_view(
    post=extend_schema(
        summary="Create a new company",
        description="Creates a new company in Xero first, then syncs locally. Requires valid Xero authentication.",
        request=CompanyCreateSerializer,
        responses={
            201: CompanyCreateResponseSerializer,
            400: CompanyErrorResponseSerializer,
            401: CompanyErrorResponseSerializer,
            409: CompanyDuplicateErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    )
)
class CompanyCreateRestView(APIView):
    """
    REST view for creating new companies.
    Follows clean code principles and delegates to service layer.
    Creates company in Xero first, then syncs locally.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanyCreateResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "POST":
            return CompanyCreateSerializer
        return CompanyCreateResponseSerializer

    def post(self, request: Request) -> Response:
        """
        Create a new company, first in Xero, then sync locally.
        """
        try:
            # Validate input data
            input_serializer = CompanyCreateSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": f"Invalid input data: {input_serializer.errors}"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            validated_data = input_serializer.validated_data
            created_company = CompanyRestService.create_company(validated_data)
            created_company = (
                Company.objects.with_invoice_summary()
                .annotate(
                    phone=ContactMethod.primary_phone_annotation(
                        owner="company", outer_ref="pk"
                    )
                )
                .get(id=created_company.id)
            )

            response_data = {
                "success": True,
                "company": CompanyRestService._format_company_summary(created_company),
                "message": f'Company "{created_company.name}" created successfully',
            }

            response_serializer = CompanyCreateResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            logger.error(
                f"Error during company creation: {e} | Request data: {request.data}"
            )
            # Handle duplicate company error
            if "already exists in Xero" in str(e):
                # Extract company name from error message
                error_msg = str(e)
                if "Company '" in error_msg and "' already exists" in error_msg:
                    name = error_msg.split("Company '")[1].split("' already exists")[0]
                    duplicate_error_data = {
                        "error": error_msg,
                        "existing_company": {
                            "name": name,
                            "xero_contact_id": (
                                error_msg.split("ID: ")[-1]
                                if "ID: " in error_msg
                                else ""
                            ),
                        },
                    }
                    error_serializer = CompanyDuplicateErrorResponseSerializer(
                        data=duplicate_error_data
                    )
                    error_serializer.is_valid(raise_exception=True)
                    return Response(
                        error_serializer.data, status=status.HTTP_409_CONFLICT
                    )

            # Handle validation errors
            if "authentication required" in str(e).lower():
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": str(e)}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_401_UNAUTHORIZED
                )

            # Other validation errors
            error_serializer = CompanyErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _build_server_error_response(
                message="Error creating company", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get job person",
        description="Retrieve person information for a specific job.",
        parameters=[
            OpenApiParameter(
                name="job_id",
                location=OpenApiParameter.PATH,
                description="UUID of the job",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        responses={
            200: JobPersonResponseSerializer,
            404: CompanyErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    ),
    put=extend_schema(
        summary="Update job person",
        description="Update the person associated with a specific job.",
        parameters=[
            OpenApiParameter(
                name="job_id",
                location=OpenApiParameter.PATH,
                description="UUID of the job",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        request=JobPersonUpdateSerializer,
        responses={
            200: JobPersonResponseSerializer,
            400: CompanyErrorResponseSerializer,
            404: CompanyErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
        operation_id="companies_jobs_person_update",
    ),
)
class JobPersonRestView(APIView):
    """
    REST view for person information operations for a job.
    Handles both retrieving and updating the person associated with a specific job.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JobPersonResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "PUT":
            return JobPersonUpdateSerializer
        return JobPersonResponseSerializer

    def get(self, request: Request, job_id: UUID) -> Response:
        """
        Retrieves person information for a specific job.
        """
        try:
            # Guard clause: validate job_id
            if not job_id:
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": "Job ID is required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            person_data = CompanyRestService.get_job_person(job_id)
            serializer = JobPersonResponseSerializer(data=person_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except ValueError as e:
            error_serializer = CompanyErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return _build_server_error_response(
                message="Error retrieving job person", exc=exc
            )

    def put(self, request: Request, job_id: UUID) -> Response:
        """
        Updates the person for a specific job.
        """
        try:
            # Guard clause: validate job_id
            if not job_id:
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": "Job ID is required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            # Validate input data
            input_serializer = JobPersonUpdateSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": f"Invalid input data: {input_serializer.errors}"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            person_data = input_serializer.validated_data
            if not isinstance(request.user, Staff):
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": "Authentication required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_401_UNAUTHORIZED
                )
            updated_person = CompanyRestService.update_job_person(
                job_id, person_data, request.user
            )
            serializer = JobPersonResponseSerializer(data=updated_person)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except ValueError as e:
            error_serializer = CompanyErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return _build_server_error_response(
                message="Error updating job person", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get company jobs",
        description="Retrieve all jobs for a specific company.",
        parameters=[
            OpenApiParameter(
                name="company_id",
                location=OpenApiParameter.PATH,
                description="UUID of the company",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        responses={
            200: CompanyJobsResponseSerializer,
            404: CompanyErrorResponseSerializer,
            500: CompanyErrorResponseSerializer,
        },
        tags=["Companies"],
    )
)
class CompanyJobsRestView(APIView):
    """
    REST view for fetching all jobs for a specific company.
    Returns job header information for fast loading.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanyJobsResponseSerializer

    def get(self, request: Request, company_id: str) -> Response:
        """
        Retrieves all jobs for a specific company.
        """
        try:
            # Guard clause: validate company_id
            if not company_id:
                error_serializer = CompanyErrorResponseSerializer(
                    data={"error": "Company ID is required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            jobs = CompanyRestService.get_company_jobs(company_id)
            response_data = {"results": jobs}
            serializer = CompanyJobsResponseSerializer(data=response_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except ValueError as e:
            error_serializer = CompanyErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error fetching jobs for company {company_id}: {str(e)}")
            error_serializer = CompanyErrorResponseSerializer(
                data={"error": "Error fetching company jobs", "details": str(e)}
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
