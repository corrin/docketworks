from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.job.permissions import IsOfficeStaff
from apps.workflow.serializers import (
    GroupedAppErrorListResponseSerializer,
    GroupedErrorResolveRequestSerializer,
    GroupedErrorResolveResponseSerializer,
)
from apps.workflow.services.error_grouping import (
    list_grouped_app_errors,
    list_grouped_xero_errors,
    mark_app_error_group_resolved_by_fingerprint,
    mark_app_error_group_unresolved_by_fingerprint,
    mark_xero_error_group_resolved_by_fingerprint,
    mark_xero_error_group_unresolved_by_fingerprint,
)
from apps.workflow.utils import parse_pagination_params


def _parse_common_filters(request: Request) -> dict[str, Any]:
    resolved_param = request.query_params.get("resolved")
    resolved: bool | None = None
    if resolved_param is not None:
        value = resolved_param.strip().lower()
        if value in {"true", "1", "yes"}:
            resolved = True
        elif value in {"false", "0", "no"}:
            resolved = False
        else:
            raise ValueError("Invalid resolved parameter")

    severity_param = request.query_params.get("severity")
    severity: int | None = None
    if severity_param is not None:
        try:
            severity = int(severity_param)
        except ValueError as exc:
            raise ValueError(f"Invalid severity parameter: {severity_param!r}") from exc

    return {
        "app": request.query_params.get("app"),
        "severity": severity,
        "resolved": resolved,
        "job_id": request.query_params.get("job_id"),
        "user_id": request.query_params.get("user_id"),
    }


class _BaseGroupedErrorListView(APIView):
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    serializer_class = GroupedAppErrorListResponseSerializer
    list_callable = staticmethod(list_grouped_app_errors)

    @extend_schema(responses={200: GroupedAppErrorListResponseSerializer})
    def get(self, request: Request) -> Response:
        try:
            limit, offset = parse_pagination_params(request)
            filters = _parse_common_filters(request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = self.list_callable(limit=limit, offset=offset, **filters)
        serializer = self.serializer_class(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AppErrorGroupedListView(_BaseGroupedErrorListView):
    list_callable = staticmethod(list_grouped_app_errors)


class XeroErrorGroupedListView(_BaseGroupedErrorListView):
    list_callable = staticmethod(list_grouped_xero_errors)


class _BaseGroupedErrorResolveView(APIView):
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    request_serializer = GroupedErrorResolveRequestSerializer
    response_serializer = GroupedErrorResolveResponseSerializer

    # Subclasses set resolve_callable.
    resolve_callable = staticmethod(mark_app_error_group_resolved_by_fingerprint)

    @extend_schema(
        request=GroupedErrorResolveRequestSerializer,
        responses={200: GroupedErrorResolveResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        body = self.request_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        assert isinstance(request.user, Staff)
        staff = request.user
        updated = self.resolve_callable(body.validated_data["fingerprint"], staff)
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class AppErrorGroupedMarkResolvedView(_BaseGroupedErrorResolveView):
    resolve_callable = staticmethod(mark_app_error_group_resolved_by_fingerprint)


class AppErrorGroupedMarkUnresolvedView(_BaseGroupedErrorResolveView):
    resolve_callable = staticmethod(mark_app_error_group_unresolved_by_fingerprint)


class XeroErrorGroupedMarkResolvedView(_BaseGroupedErrorResolveView):
    resolve_callable = staticmethod(mark_xero_error_group_resolved_by_fingerprint)


class XeroErrorGroupedMarkUnresolvedView(_BaseGroupedErrorResolveView):
    resolve_callable = staticmethod(mark_xero_error_group_unresolved_by_fingerprint)
