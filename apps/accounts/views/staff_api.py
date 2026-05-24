import logging

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Staff
from apps.accounts.permissions import IsStaff
from apps.accounts.serializers import StaffCreateSerializer, StaffSerializer

logger = logging.getLogger(__name__)


@extend_schema(
    summary="List and create staff members",
    description="API endpoint for listing all staff members and creating new staff members. "
    "Supports multipart/form data for file uploads (e.g., profile pictures).",
    tags=["Staff Management"],
    examples=[
        OpenApiExample(
            "Create Staff Member",
            value={
                "email": "john.doe@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "preferred_name": "Johnny",
                "password": "securepassword123",
                "wage_rate": "25.50",
                "is_office_staff": True,
                "hours_mon": "8.00",
                "hours_tue": "8.00",
                "hours_wed": "8.00",
                "hours_thu": "8.00",
                "hours_fri": "8.00",
                "hours_sat": "0.00",
                "hours_sun": "0.00",
            },
            request_only=True,
        ),
    ],
)
class StaffListCreateAPIView(generics.ListCreateAPIView):
    """API endpoint for listing and creating staff members.

    Supports both GET (list all staff) and POST (create new staff) operations.
    Requires authentication and staff permissions. Handles multipart/form data
    for file uploads (e.g., profile pictures).
    """

    queryset = Staff.objects.all()
    permission_classes = [IsAuthenticated, IsStaff]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return Staff.objects.prefetch_related(
            "groups",
            "user_permissions",
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StaffCreateSerializer
        return StaffSerializer

    @extend_schema(
        summary="Create a new staff member",
        description="Create a new staff member with the provided details. "
        "Supports multipart/form data for file uploads (e.g., profile pictures).",
        tags=["Staff Management"],
        request=StaffCreateSerializer,
        responses={201: StaffSerializer},
    )
    def post(self, request, *args, **kwargs):
        try:
            logger.info(f"[StaffCreate] Method: {request.method}")
            logger.info(f"[StaffCreate] Received data: {request.data}")
            return super().post(request, *args, **kwargs)
        except ValidationError as e:
            logger.error(f"[StaffCreate] Error during staff creation: {str(e)}")
            return Response(
                e.detail,
                status=status.HTTP_400_BAD_REQUEST,
            )


@extend_schema(
    summary="Retrieve, update, or delete staff member",
    description="API endpoint for retrieving, updating, and deleting individual staff members. "
    "Supports GET (retrieve), PUT/PATCH (update), and DELETE operations. "
    "Includes comprehensive logging for update operations and handles multipart/form data for file uploads.",
    tags=["Staff Management"],
    examples=[
        OpenApiExample(
            "Update Staff Member",
            value={
                "first_name": "Jane",
                "last_name": "Smith",
                "preferred_name": "Janie",
                "wage_rate": "28.00",
                "hours_mon": "7.50",
                "hours_tue": "7.50",
                "hours_wed": "7.50",
                "hours_thu": "7.50",
                "hours_fri": "7.50",
            },
            request_only=True,
        ),
    ],
)
class StaffRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    """API endpoint for retrieving, updating, and deleting individual staff members.

    Supports GET (retrieve), PUT/PATCH (update), and DELETE operations on
    specific staff members. Includes comprehensive logging for update operations
    and handles multipart/form data for file uploads.
    """

    queryset = Staff.objects.all()
    serializer_class = StaffSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return Staff.objects.prefetch_related(
            "groups",
            "user_permissions",
        )

    def update(self, request, *args, **kwargs):
        logger = logging.getLogger("workflow")
        staff_id = kwargs.get("pk")
        logger.info(f"[StaffUpdate] Method: {request.method} | Staff ID: {staff_id}")
        logger.info(f"[StaffUpdate] Received data: {request.data}")
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            logger.error(f"[StaffUpdate] Validation errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_update(serializer)
        logger.info(f"[StaffUpdate] Successfully updated Staff ID: {staff_id}")
        return Response(serializer.data)
