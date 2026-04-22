"""
Cache-state control endpoints used by the E2E test harness.

`POST /api/disable_cache/?resume_after=<seconds>` forces every request to
invalidate singleton caches until the specified resume time (default 1h).
`POST /api/enable_cache/` clears the flag immediately. Playwright's
globalSetup/globalTeardown call these; the TTL on disable is a safety net
so a crashed teardown can't leave caching off forever.
"""

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workflow.models import CacheState
from apps.workflow.services.error_persistence import persist_app_error


class DisableCacheAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="DisableCacheResponse",
                fields={"disabled_until": serializers.DateTimeField()},
            )
        },
    )
    def post(self, request: Request) -> Response:
        try:
            seconds = int(request.query_params.get("resume_after", 3600))
        except (TypeError, ValueError) as exc:
            persist_app_error(exc)
            return Response(
                {"detail": "resume_after must be an integer number of seconds"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if seconds <= 0:
            return Response(
                {"detail": "resume_after must be positive"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        until = timezone.now() + timedelta(seconds=seconds)
        CacheState.objects.update_or_create(pk=1, defaults={"disabled_until": until})
        return Response({"disabled_until": until.isoformat()})


class EnableCacheAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="EnableCacheResponse",
                fields={"enabled": serializers.BooleanField()},
            )
        },
    )
    def post(self, request: Request) -> Response:
        CacheState.objects.update_or_create(pk=1, defaults={"disabled_until": None})
        return Response({"enabled": True})
