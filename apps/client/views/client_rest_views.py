"""
Client REST Views

REST views for the Client module following clean code principles:
- SRP (Single Responsibility Principle)
- Early return and guard clauses
- Delegation to service layer
- Views as orchestrators only
"""

import logging
from typing import Any, Dict

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

from apps.client.serializers import (
    ClientCreateResponseSerializer,
    ClientCreateSerializer,
    ClientDetailResponseSerializer,
    ClientDuplicateErrorResponseSerializer,
    ClientErrorResponseSerializer,
    ClientJobsResponseSerializer,
    ClientListResponseSerializer,
    ClientNameOnlySerializer,
    ClientSearchResponseSerializer,
    ClientUpdateResponseSerializer,
    ClientUpdateSerializer,
    JobContactResponseSerializer,
    JobContactUpdateSerializer,
)
from apps.client.services.client_rest_service import ClientRestService
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

    serializer = ClientErrorResponseSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    return Response(serializer.data, status=status_code)


@extend_schema_view(
    get=extend_schema(
        summary="List all clients",
        description="Returns a list of all clients with basic information (id and name) for dropdowns and search.",
        responses={
            200: ClientNameOnlySerializer(many=True),
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    )
)
class ClientListAllRestView(APIView):
    """
    REST view for listing all clients.
    Used by dropdowns and advanced search.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClientListResponseSerializer

    def get(self, request: Request) -> Response:
        """
        Lists all clients (only id and name) for fast dropdowns.
        """
        try:
            clients_data = ClientRestService.get_all_clients()
            return Response(clients_data)
        except Exception as exc:
            return _build_server_error_response(
                message="Error fetching all clients", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Search clients",
        parameters=[
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search query (case-insensitive substring match). If empty, returns all clients.",
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
            200: ClientSearchResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    )
)
class ClientSearchRestView(APIView):
    """
    REST view for client search with pagination and sorting.
    Returns all clients when no search query provided.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClientSearchResponseSerializer

    def get(self, request: Request) -> Response:
        """
        Lists/searches clients with pagination and sorting.
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
            result = ClientRestService.list_clients(
                query=query if len(query) >= 3 else None,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_dir=sort_dir,
            )

            serializer = ClientSearchResponseSerializer(data=result)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except Exception as exc:
            return _build_server_error_response(
                message="Error searching clients", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get client details",
        description="Retrieve detailed information for a specific client.",
        parameters=[
            OpenApiParameter(
                name="client_id",
                location=OpenApiParameter.PATH,
                description="UUID of the client",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        responses={
            200: ClientDetailResponseSerializer,
            404: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    )
)
class ClientRetrieveRestView(APIView):
    """
    REST view for retrieving a specific client by ID.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClientDetailResponseSerializer

    def get(self, request: Request, client_id: str) -> Response:
        """
        Retrieves detailed information for a specific client.
        """
        try:
            client_data = ClientRestService.get_client_by_id(client_id)
            return Response(client_data)
        except ValueError as e:
            error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return _build_server_error_response(
                message="Error retrieving client", exc=exc
            )


@extend_schema_view(
    put=extend_schema(
        summary="Update client",
        description="Update an existing client's information.",
        parameters=[
            OpenApiParameter(
                name="client_id",
                location=OpenApiParameter.PATH,
                description="UUID of the client",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        request=ClientUpdateSerializer,
        responses={
            200: ClientUpdateResponseSerializer,
            400: ClientErrorResponseSerializer,
            404: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    ),
    patch=extend_schema(
        summary="Partially update client",
        description="Partially update an existing client's information.",
        parameters=[
            OpenApiParameter(
                name="client_id",
                location=OpenApiParameter.PATH,
                description="UUID of the client",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        request=ClientUpdateSerializer,
        responses={
            200: ClientUpdateResponseSerializer,
            400: ClientErrorResponseSerializer,
            404: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    ),
)
class ClientUpdateRestView(APIView):
    """
    REST view for updating client information.
    Supports both PUT (full update) and PATCH (partial update).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClientUpdateResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method in ["PUT", "PATCH"]:
            return ClientUpdateSerializer
        return ClientUpdateResponseSerializer

    def put(self, request: Request, client_id: str) -> Response:
        """
        Full update of client information.
        """
        return self._update_client(request, client_id, partial=False)

    def patch(self, request: Request, client_id: str) -> Response:
        """
        Partial update of client information.
        """
        return self._update_client(request, client_id, partial=True)

    def _update_client(
        self, request: Request, client_id: str, partial: bool = True
    ) -> Response:
        """
        Common method for handling client updates.
        """
        try:
            # Validate input data
            input_serializer = ClientUpdateSerializer(
                data=request.data, partial=partial
            )
            if not input_serializer.is_valid():
                error_serializer = ClientErrorResponseSerializer(
                    data={"error": f"Invalid input data: {input_serializer.errors}"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            validated_data = input_serializer.validated_data
            updated_client = ClientRestService.update_client(client_id, validated_data)

            # Format response using the service method
            client_data = ClientRestService._format_client_detail(updated_client)
            response_data = {
                "success": True,
                "client": client_data,
                "message": f'Client "{updated_client.name}" updated successfully',
            }

            response_serializer = ClientUpdateResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data)

        except ValueError as e:
            # Handle not found and validation errors
            if "not found" in str(e).lower():
                error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
            else:
                error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as exc:
            return _build_server_error_response(
                message="Error updating client", exc=exc
            )


@extend_schema_view(
    post=extend_schema(
        summary="Create a new client",
        description="Creates a new client in Xero first, then syncs locally. Requires valid Xero authentication.",
        request=ClientCreateSerializer,
        responses={
            201: ClientCreateResponseSerializer,
            400: ClientErrorResponseSerializer,
            401: ClientErrorResponseSerializer,
            409: ClientDuplicateErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    )
)
class ClientCreateRestView(APIView):
    """
    REST view for creating new clients.
    Follows clean code principles and delegates to service layer.
    Creates client in Xero first, then syncs locally.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClientCreateResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "POST":
            return ClientCreateSerializer
        return ClientCreateResponseSerializer

    def post(self, request: Request) -> Response:
        """
        Create a new client, first in Xero, then sync locally.
        """
        try:
            # Validate input data
            input_serializer = ClientCreateSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_serializer = ClientErrorResponseSerializer(
                    data={"error": f"Invalid input data: {input_serializer.errors}"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            validated_data = input_serializer.validated_data
            created_client = ClientRestService.create_client(validated_data)

            response_data = {
                "success": True,
                "client": ClientRestService._format_client_summary(created_client),
                "message": f'Client "{created_client.name}" created successfully',
            }

            response_serializer = ClientCreateResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            logger.error(
                f"Error during client creation: {e} | Request data: {request.data}"
            )
            # Handle duplicate client error
            if "already exists in Xero" in str(e):
                # Extract client name from error message
                error_msg = str(e)
                if "Client '" in error_msg and "' already exists" in error_msg:
                    name = error_msg.split("Client '")[1].split("' already exists")[0]
                    duplicate_error_data = {
                        "error": error_msg,
                        "existing_client": {
                            "name": name,
                            "xero_contact_id": (
                                error_msg.split("ID: ")[-1]
                                if "ID: " in error_msg
                                else ""
                            ),
                        },
                    }
                    error_serializer = ClientDuplicateErrorResponseSerializer(
                        data=duplicate_error_data
                    )
                    error_serializer.is_valid(raise_exception=True)
                    return Response(
                        error_serializer.data, status=status.HTTP_409_CONFLICT
                    )

            # Handle validation errors
            if "authentication required" in str(e).lower():
                error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_401_UNAUTHORIZED
                )

            # Other validation errors
            error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _build_server_error_response(
                message="Error creating client", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get job contact",
        description="Retrieve contact information for a specific job.",
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
            200: JobContactResponseSerializer,
            404: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    ),
    put=extend_schema(
        summary="Update job contact",
        description="Update the contact person associated with a specific job.",
        parameters=[
            OpenApiParameter(
                name="job_id",
                location=OpenApiParameter.PATH,
                description="UUID of the job",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        request=JobContactUpdateSerializer,
        responses={
            200: JobContactResponseSerializer,
            400: ClientErrorResponseSerializer,
            404: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
        operation_id="clients_jobs_contact_update",
    ),
)
class JobContactRestView(APIView):
    """
    REST view for contact information operations for a job.
    Handles both retrieving and updating the contact associated with a specific job.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JobContactResponseSerializer

    def get_serializer_class(self):
        """Return the appropriate serializer class based on the request method"""
        if self.request.method == "PUT":
            return JobContactUpdateSerializer
        return JobContactResponseSerializer

    def get(self, request: Request, job_id: str) -> Response:
        """
        Retrieves contact information for a specific job.
        """
        try:
            # Guard clause: validate job_id
            if not job_id:
                error_serializer = ClientErrorResponseSerializer(
                    data={"error": "Job ID is required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            contact_data = ClientRestService.get_job_contact(job_id)
            serializer = JobContactResponseSerializer(data=contact_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except ValueError as e:
            error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return _build_server_error_response(
                message="Error retrieving job contact", exc=exc
            )

    def put(self, request: Request, job_id: str) -> Response:
        """
        Updates the contact person for a specific job.
        """
        try:
            # Guard clause: validate job_id
            if not job_id:
                error_serializer = ClientErrorResponseSerializer(
                    data={"error": "Job ID is required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            # Validate input data
            input_serializer = JobContactUpdateSerializer(data=request.data)
            if not input_serializer.is_valid():
                error_serializer = ClientErrorResponseSerializer(
                    data={"error": f"Invalid input data: {input_serializer.errors}"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            contact_data = input_serializer.validated_data
            updated_contact = ClientRestService.update_job_contact(
                job_id, contact_data, request.user
            )
            serializer = JobContactResponseSerializer(data=updated_contact)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except ValueError as e:
            error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            return _build_server_error_response(
                message="Error updating job contact", exc=exc
            )


@extend_schema_view(
    get=extend_schema(
        summary="Get client jobs",
        description="Retrieve all jobs for a specific client.",
        parameters=[
            OpenApiParameter(
                name="client_id",
                location=OpenApiParameter.PATH,
                description="UUID of the client",
                required=True,
                type=OpenApiTypes.UUID,
            )
        ],
        responses={
            200: ClientJobsResponseSerializer,
            404: ClientErrorResponseSerializer,
            500: ClientErrorResponseSerializer,
        },
        tags=["Clients"],
    )
)
class ClientJobsRestView(APIView):
    """
    REST view for fetching all jobs for a specific client.
    Returns job header information for fast loading.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ClientJobsResponseSerializer

    def get(self, request: Request, client_id: str) -> Response:
        """
        Retrieves all jobs for a specific client.
        """
        try:
            # Guard clause: validate client_id
            if not client_id:
                error_serializer = ClientErrorResponseSerializer(
                    data={"error": "Client ID is required"}
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            jobs = ClientRestService.get_client_jobs(client_id)
            response_data = {"results": jobs}
            serializer = ClientJobsResponseSerializer(data=response_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)

        except ValueError as e:
            error_serializer = ClientErrorResponseSerializer(data={"error": str(e)})
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error fetching jobs for client {client_id}: {str(e)}")
            error_serializer = ClientErrorResponseSerializer(
                data={"error": "Error fetching client jobs", "details": str(e)}
            )
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
