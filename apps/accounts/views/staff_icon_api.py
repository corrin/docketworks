import logging
import os

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.accounts.permissions import IsStaff
from apps.accounts.serializers import StaffSerializer
from apps.workflow.views.company_defaults_logo_api import (
    ALLOWED_EXTENSIONS,
    MAX_UPLOAD_SIZE,
)

logger = logging.getLogger(__name__)


class StaffIconAPIView(APIView):
    """Upload or remove the profile picture for a single staff member.

    Errors are persisted by the project-wide DRF exception handler, which has
    the request context (user, session replay id, path). Persisting here first
    would win the "first write wins" race in persist_app_error and record the
    failure without any of it, so this view deliberately has no try/except.
    """

    serializer_class = StaffSerializer
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated, IsStaff]

    @extend_schema(
        summary="Upload a staff profile picture",
        description="Replace a staff member's profile picture. This is a "
        "separate endpoint because the staff resource itself is JSON-only — a "
        "file cannot ride inside a JSON body.",
        tags=["Staff Management"],
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"file": {"type": "string", "format": "binary"}},
                "required": ["file"],
            }
        },
        responses={200: StaffSerializer},
    )
    def post(self, request: Request, pk: str) -> Response:
        staff = Staff.objects.filter(pk=pk).first()
        if staff is None:
            return Response({"error": "Staff member not found"}, status=404)

        file = request.data.get("file")
        if not file:
            return Response({"error": "No file provided"}, status=400)

        if file.size > MAX_UPLOAD_SIZE:
            return Response({"error": "File too large (max 5MB)"}, status=400)

        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response({"error": f"Unsupported file type: {ext}"}, status=400)

        # Drop the previous image so replacing a picture does not orphan a file.
        # Every staff icon is a user upload under MEDIA_ROOT/staff_icons, so
        # unlike company logos there is no shipped baseline asset to protect.
        staff.icon.delete(save=False)
        staff.icon = file
        staff.save(update_fields=["icon"])

        logger.info(f"[StaffIcon] Updated icon for Staff ID: {pk}")
        return Response(StaffSerializer(staff, context={"request": request}).data)

    @extend_schema(
        summary="Remove a staff profile picture",
        description="Clear a staff member's profile picture and delete the "
        "image from disk. Idempotent: removing an absent picture succeeds, "
        "because the requested end state already holds.",
        tags=["Staff Management"],
        responses={200: StaffSerializer},
    )
    def delete(self, request: Request, pk: str) -> Response:
        staff = Staff.objects.filter(pk=pk).first()
        if staff is None:
            return Response({"error": "Staff member not found"}, status=404)

        # FieldFile.delete() returns early when there is no file and clears the
        # field itself, so this needs no guard and is idempotent.
        staff.icon.delete(save=False)
        staff.save(update_fields=["icon"])

        logger.info(f"[StaffIcon] Removed icon for Staff ID: {pk}")
        return Response(StaffSerializer(staff, context={"request": request}).data)
