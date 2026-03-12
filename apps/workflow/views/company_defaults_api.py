from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workflow.models import CompanyDefaults
from apps.workflow.serializers import CompanyDefaultsSerializer


class CompanyDefaultsAPIView(APIView):
    """
    API view for managing company default settings.

    This view provides endpoints to retrieve and update the company's default
    configuration settings. All authenticated users can retrieve settings,
    but only authenticated users can update them.

    Endpoints:
        GET: Retrieve current company defaults
        PUT: Update all company defaults (full update)
        PATCH: Partially update company defaults

    Permissions:
        - IsAuthenticated: Any logged-in user can access this API

    Returns:
        Company defaults data serialized using CompanyDefaultsSerializer
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CompanyDefaultsSerializer

    def get(self, request):
        instance = CompanyDefaults.get_solo()
        serializer = CompanyDefaultsSerializer(instance)
        return Response(serializer.data)

    def put(self, request):
        # Extract data from 'body' wrapper if it exists (Zodios sends data wrapped in 'body')
        request_data = (
            request.data.get("body", request.data)
            if isinstance(request.data, dict) and "body" in request.data
            else request.data
        )

        instance = CompanyDefaults.get_solo()
        serializer = CompanyDefaultsSerializer(
            instance, data=request_data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def patch(self, request):
        # Extract data from 'body' wrapper if it exists (Zodios sends data wrapped in 'body')
        request_data = (
            request.data.get("body", request.data)
            if isinstance(request.data, dict) and "body" in request.data
            else request.data
        )

        instance = CompanyDefaults.get_solo()
        serializer = CompanyDefaultsSerializer(
            instance, data=request_data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
