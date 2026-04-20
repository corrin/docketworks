"""
API endpoint returning the currently deployed backend build ID (git SHA).

Used by the frontend to detect when the backend has been redeployed while a
tab has been left open; on mismatch with its own compiled-in build ID the
frontend hard-reloads.
"""

from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class BuildIdAPIView(APIView):
    """Return the git SHA of the running backend process."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses={
            200: inline_serializer(
                name="BuildId",
                fields={"build_id": serializers.CharField()},
            )
        },
    )
    def get(self, request: Request) -> Response:
        response = Response({"build_id": settings.BUILD_ID})
        response["Cache-Control"] = "no-store"
        return response
