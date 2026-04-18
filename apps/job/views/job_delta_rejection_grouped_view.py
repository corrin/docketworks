from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.job_serializer import (
    GroupedJobDeltaRejectionListResponseSerializer,
    GroupedJobDeltaRejectionResolveRequestSerializer,
    GroupedJobDeltaRejectionResolveResponseSerializer,
)
from apps.job.services.job_rest_service import JobRestService


def _parse_pagination(request: Request) -> tuple[int, int]:
    try:
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid pagination parameters") from exc
    return limit, offset


def _parse_resolved(request: Request) -> bool | None:
    resolved_param = request.query_params.get("resolved")
    if resolved_param is None:
        return None
    value = resolved_param.strip().lower()
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    raise ValueError("Invalid resolved parameter")


class JobDeltaRejectionGroupedListView(APIView):
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = GroupedJobDeltaRejectionListResponseSerializer

    @extend_schema(
        responses={200: GroupedJobDeltaRejectionListResponseSerializer},
        tags=["Jobs"],
    )
    def get(self, request: Request) -> Response:
        try:
            limit, offset = _parse_pagination(request)
            resolved = _parse_resolved(request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = JobRestService.list_grouped_job_delta_rejections(
            limit=limit,
            offset=offset,
            job_id=request.query_params.get("job_id"),
            resolved=resolved,
        )
        serializer = self.serializer_class(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class _BaseJobDeltaRejectionResolveView(APIView):
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    resolve = True  # subclasses override

    @extend_schema(
        request=GroupedJobDeltaRejectionResolveRequestSerializer,
        responses={200: GroupedJobDeltaRejectionResolveResponseSerializer},
        tags=["Jobs"],
    )
    def post(self, request: Request) -> Response:
        body = GroupedJobDeltaRejectionResolveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        assert isinstance(request.user, Staff)
        staff = request.user
        reason = body.validated_data["reason"]
        if self.resolve:
            updated = JobRestService.mark_job_delta_rejection_group_resolved(
                reason, staff
            )
        else:
            updated = JobRestService.mark_job_delta_rejection_group_unresolved(
                reason, staff
            )
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class JobDeltaRejectionGroupedMarkResolvedView(_BaseJobDeltaRejectionResolveView):
    resolve = True


class JobDeltaRejectionGroupedMarkUnresolvedView(_BaseJobDeltaRejectionResolveView):
    resolve = False
