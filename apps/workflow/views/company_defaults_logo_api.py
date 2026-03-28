import os

from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workflow.models import CompanyDefaults
from apps.workflow.serializers import CompanyDefaultsSerializer
from apps.workflow.services.error_persistence import persist_app_error

ALLOWED_LOGO_FIELDS = {"logo", "logo_wide"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


class CompanyDefaultsLogoAPIView(APIView):
    """
    API view for uploading and deleting company logo images.

    POST: Upload a logo image to a specified field.
    DELETE: Clear a logo field and remove the file from disk.
    """

    serializer_class = CompanyDefaultsSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        field_name = request.data.get("field_name")
        if field_name not in ALLOWED_LOGO_FIELDS:
            return Response(
                {
                    "error": f"field_name must be one of: {', '.join(sorted(ALLOWED_LOGO_FIELDS))}"
                },
                status=400,
            )

        file = request.data.get("file")
        if not file:
            return Response({"error": "No file provided"}, status=400)

        if file.size > MAX_UPLOAD_SIZE:
            return Response({"error": "File too large (max 5MB)"}, status=400)

        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response(
                {"error": f"Unsupported file type: {ext}"},
                status=400,
            )

        try:
            instance = CompanyDefaults.get_solo()

            # Delete old file if one exists
            old_file = getattr(instance, field_name)
            if old_file:
                try:
                    os.remove(old_file.path)
                except FileNotFoundError:
                    pass

            setattr(instance, field_name, file)
            instance.save()
        except Exception as exc:
            persist_app_error(exc)
            raise

        serializer = CompanyDefaultsSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @extend_schema(responses={200: CompanyDefaultsSerializer})
    def delete(self, request):
        field_name = request.data.get("field_name")
        if field_name not in ALLOWED_LOGO_FIELDS:
            return Response(
                {
                    "error": f"field_name must be one of: {', '.join(sorted(ALLOWED_LOGO_FIELDS))}"
                },
                status=400,
            )

        try:
            instance = CompanyDefaults.get_solo()
            field_file = getattr(instance, field_name)

            if field_file:
                try:
                    os.remove(field_file.path)
                except FileNotFoundError:
                    pass

            setattr(instance, field_name, None)
            instance.save()
        except Exception as exc:
            persist_app_error(exc)
            raise

        serializer = CompanyDefaultsSerializer(instance, context={"request": request})
        return Response(serializer.data)
