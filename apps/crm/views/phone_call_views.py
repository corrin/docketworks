import mimetypes
from uuid import UUID

from django.db.models import Q, QuerySet
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import ErrorDetails
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.accounts.permissions import IsSuperuser
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.crm.serializers import (
    PhoneCallJobLinkPayload,
    PhoneCallRecordingSerializer,
    PhoneCallRecordSerializer,
    PhoneEndpointSerializer,
    PhoneNumberAssignmentPayload,
    PhoneProviderSettingsSerializer,
)
from apps.crm.services.phone_call_service import (
    assign_phone_number_from_call,
    delete_local_recording,
    link_phone_call_to_job,
    normalize_phone,
    provider_delete_recording,
    recording_file_path,
    unlink_phone_call_job,
)
from apps.crm.tasks import rematch_phone_calls_task
from apps.job.permissions import IsOfficeStaff
from apps.workflow.api.pagination import PageSizePagination
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

PHONE_CALL_JOB_LINK_SCHEMA = inline_serializer(
    name="PhoneCallJobLink",
    fields={"job": serializers.UUIDField()},
)

PHONE_NUMBER_ASSIGNMENT_SCHEMA = inline_serializer(
    name="PhoneNumberAssignment",
    fields={
        "client": serializers.UUIDField(),
        "contact": serializers.UUIDField(required=False, allow_null=True),
        "label": serializers.CharField(
            max_length=255,
            required=False,
            allow_blank=True,
        ),
        "is_primary": serializers.BooleanField(required=False, default=False),
    },
)


def _validation_error_detail(errors: list[ErrorDetails]) -> dict[str, list[str]]:
    detail: dict[str, list[str]] = {}
    for error in errors:
        location = error["loc"]
        field_name = str(location[0]) if location else "non_field_errors"
        detail.setdefault(field_name, []).append(error["msg"])
    return detail


def _query_uuid(value: str | None, field_name: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValidationError({field_name: ["Must be a valid UUID."]}) from exc


def _phone_call_filter_kwargs(request: Request) -> dict[str, UUID]:
    query_filters = (
        ("client_id", _query_uuid(request.query_params.get("client"), "client")),
        ("contact_id", _query_uuid(request.query_params.get("contact"), "contact")),
        ("job_id", _query_uuid(request.query_params.get("job"), "job")),
        (
            "origin_endpoint_id",
            _query_uuid(request.query_params.get("origin_endpoint"), "origin_endpoint"),
        ),
        (
            "destination_endpoint_id",
            _query_uuid(
                request.query_params.get("destination_endpoint"),
                "destination_endpoint",
            ),
        ),
    )
    filter_kwargs: dict[str, UUID] = {}
    for lookup, value in query_filters:
        if value is None:
            continue
        filter_kwargs[lookup] = value
    return filter_kwargs


def _query_choice(value: str | None, field_name: str, allowed: set[str]) -> str:
    if not value:
        return "all"
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValidationError({field_name: [f"Must be one of: {allowed_values}."]})
    return value


def _query_bool(value: str | None, field_name: str) -> bool | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValidationError({field_name: ["Must be true or false."]})


def _query_date(value: str | None, field_name: str):
    if not value:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationError({field_name: ["Must be a valid date."]})
    return parsed


def _apply_client_match_filter(
    queryset: QuerySet[PhoneCallRecord],
    client_match: str,
) -> QuerySet[PhoneCallRecord]:
    if client_match == "matched":
        return queryset.filter(client_id__isnull=False)
    if client_match == "unmatched":
        return queryset.filter(client_id__isnull=True)
    return queryset


def _apply_job_link_filter(
    queryset: QuerySet[PhoneCallRecord],
    job_link: str,
) -> QuerySet[PhoneCallRecord]:
    if job_link == "linked":
        return queryset.filter(job_id__isnull=False)
    if job_link == "unlinked":
        return queryset.filter(job_id__isnull=True)
    return queryset


def _apply_direction_filter(
    queryset: QuerySet[PhoneCallRecord],
    direction: str,
) -> QuerySet[PhoneCallRecord]:
    if direction == "all":
        return queryset
    if direction in {"inbound", "outbound", "internal", "unknown"}:
        return queryset.filter(direction=direction)
    raise RuntimeError(f"Unhandled phone call direction filter: {direction}")


def _apply_recording_filter(
    queryset: QuerySet[PhoneCallRecord],
    has_recording: bool | None,
) -> QuerySet[PhoneCallRecord]:
    if has_recording is None:
        return queryset
    return queryset.filter(recording__isnull=not has_recording)


def _apply_date_filters(
    queryset: QuerySet[PhoneCallRecord],
    request: Request,
) -> QuerySet[PhoneCallRecord]:
    from_date = _query_date(request.query_params.get("from_date"), "from_date")
    to_date = _query_date(request.query_params.get("to_date"), "to_date")
    if from_date:
        queryset = queryset.filter(call_date__gte=from_date)
    if to_date:
        queryset = queryset.filter(call_date__lte=to_date)
    return queryset


def _apply_search_filter(
    queryset: QuerySet[PhoneCallRecord],
    query: str | None,
) -> QuerySet[PhoneCallRecord]:
    if not query:
        return queryset
    search = query.strip()
    if not search:
        return queryset

    normalized_phone = normalize_phone(search)
    filters = (
        Q(client__name__icontains=search)
        | Q(contact__name__icontains=search)
        | Q(origin_endpoint__label__icontains=search)
        | Q(destination_endpoint__label__icontains=search)
        | Q(job__name__icontains=search)
        | Q(origin__icontains=search)
        | Q(destination__icontains=search)
        | Q(description__icontains=search)
    )
    if normalized_phone:
        filters |= Q(origin=normalized_phone) | Q(destination=normalized_phone)
    if search.isdecimal():
        filters |= Q(job__job_number=int(search))
    return queryset.filter(filters)


def _filter_phone_call_queryset(
    queryset: QuerySet[PhoneCallRecord],
    request: Request,
) -> QuerySet[PhoneCallRecord]:
    client_match = _query_choice(
        request.query_params.get("client_match"),
        "client_match",
        {"all", "matched", "unmatched"},
    )
    job_link = _query_choice(
        request.query_params.get("job_link"),
        "job_link",
        {"all", "linked", "unlinked"},
    )
    direction = _query_choice(
        request.query_params.get("direction"),
        "direction",
        {"all", "inbound", "outbound", "internal", "unknown"},
    )
    has_recording = _query_bool(
        request.query_params.get("has_recording"), "has_recording"
    )

    queryset = _apply_client_match_filter(queryset, client_match)
    queryset = _apply_job_link_filter(queryset, job_link)
    queryset = _apply_direction_filter(queryset, direction)
    queryset = _apply_recording_filter(queryset, has_recording)
    queryset = _apply_date_filters(queryset, request)
    return _apply_search_filter(queryset, request.query_params.get("q"))


class PhoneCallRecordViewSet(viewsets.ReadOnlyModelViewSet[PhoneCallRecord]):
    serializer_class = PhoneCallRecordSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    pagination_class = PageSizePagination

    @extend_schema(
        parameters=[
            OpenApiParameter("client", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("contact", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("job", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter(
                "origin_endpoint", OpenApiTypes.UUID, OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                "destination_endpoint", OpenApiTypes.UUID, OpenApiParameter.QUERY
            ),
            OpenApiParameter("client_match", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("job_link", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("direction", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter(
                "has_recording", OpenApiTypes.BOOL, OpenApiParameter.QUERY
            ),
            OpenApiParameter("from_date", OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter("to_date", OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter("q", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter("page_size", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        tags=["CRM"],
    )
    def list(self, request: Request, *args: str, **kwargs: str) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        calls = list(page if page is not None else queryset)
        context = self.get_serializer_context()
        context["phone_recordings_by_call_id"] = {
            recording.call_id: recording
            for recording in PhoneCallRecording.objects.filter(
                call_id__in=[call.id for call in calls]
            )
        }
        serializer = self.get_serializer(calls, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def get_queryset(self) -> QuerySet[PhoneCallRecord]:
        queryset = (
            PhoneCallRecord.objects.select_related(
                "client",
                "contact",
                "job",
                "job_linked_by",
                "origin_endpoint",
                "destination_endpoint",
            )
            .filter(Q(origin__gt="") | Q(destination__gt=""))
            .order_by("-call_datetime")
        )
        queryset = queryset.filter(**_phone_call_filter_kwargs(self.request))
        return _filter_phone_call_queryset(queryset, self.request)

    @extend_schema(
        operation_id="linkPhoneCallJob",
        request=PHONE_CALL_JOB_LINK_SCHEMA,
        responses={200: PhoneCallRecordSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="job-link")
    def link_job(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        try:
            payload = PhoneCallJobLinkPayload.model_validate(request.data)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_error_detail(exc.errors())) from exc
        user = request.user
        if not isinstance(user, Staff):
            raise ValidationError({"user": ["Authenticated staff user is required."]})
        try:
            call = link_phone_call_to_job(
                call_id=str(pk),
                job_id=str(payload.job),
                linked_by=user,
            )
            response_serializer = self.get_serializer(call)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response(
                {"status": "error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

    @extend_schema(
        operation_id="unlinkPhoneCallJob",
        responses={200: PhoneCallRecordSerializer},
        tags=["CRM"],
    )
    @link_job.mapping.delete
    def unlink_job(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        try:
            call = unlink_phone_call_job(call_id=str(pk))
            response_serializer = self.get_serializer(call)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response(
                {"status": "error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

    @extend_schema(
        operation_id="assignPhoneCallNumber",
        request=PHONE_NUMBER_ASSIGNMENT_SCHEMA,
        responses={200: PhoneCallRecordSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="assign-number")
    def assign_number(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        try:
            payload = PhoneNumberAssignmentPayload.model_validate(request.data)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_error_detail(exc.errors())) from exc
        try:
            call = assign_phone_number_from_call(
                call_id=str(pk),
                client_id=str(payload.client),
                contact_id=str(payload.contact) if payload.contact else None,
                label=payload.label,
                is_primary=payload.is_primary,
            )
            response_serializer = self.get_serializer(call)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response(
                {"status": "error", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc


class PhoneCallRecordingViewSet(viewsets.ReadOnlyModelViewSet[PhoneCallRecording]):
    serializer_class = PhoneCallRecordingSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    def get_permissions(self):
        if self.action in {"delete_local_file", "delete_provider_file"}:
            return [IsAuthenticated(), IsSuperuser()]
        return super().get_permissions()

    def get_queryset(self) -> QuerySet[PhoneCallRecording]:
        return PhoneCallRecording.objects.order_by("-call__call_datetime")

    @extend_schema(
        operation_id="downloadPhoneCallRecording",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Binary recording content",
            ),
            404: OpenApiResponse(description="Recording file not found"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="download")
    def download(
        self,
        request: Request,
        pk: str | None = None,
    ) -> FileResponse | Response:
        recording = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            full_path = recording_file_path(recording)
            response = FileResponse(open(full_path, "rb"))
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type:
                response["Content-Type"] = content_type
            response["Content-Disposition"] = f'inline; filename="{recording.filename}"'
            return response
        except FileNotFoundError:
            return Response(
                {"status": "error", "message": "Recording file not found on disk"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            app_error = persist_app_error(exc)
            raise AlreadyLoggedException(exc, app_error.id) from exc

    @extend_schema(
        operation_id="deleteLocalPhoneCallRecording",
        responses={204: OpenApiResponse(description="Local recording deleted")},
        tags=["CRM"],
    )
    @action(detail=True, methods=["delete"], url_path="local-file")
    def delete_local_file(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        recording = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            delete_local_recording(recording)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            app_error = persist_app_error(exc)
            raise AlreadyLoggedException(exc, app_error.id) from exc

    @extend_schema(
        operation_id="deleteProviderPhoneCallRecording",
        responses={204: OpenApiResponse(description="Provider recording deleted")},
        tags=["CRM"],
    )
    @action(detail=True, methods=["delete"], url_path="provider-file")
    def delete_provider_file(
        self,
        request: Request,
        pk: str | None = None,
    ) -> Response:
        recording = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            provider_delete_recording(recording)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            app_error = persist_app_error(exc)
            raise AlreadyLoggedException(exc, app_error.id) from exc


class PhoneEndpointViewSet(viewsets.ModelViewSet[PhoneEndpoint]):
    serializer_class = PhoneEndpointSerializer
    permission_classes = [IsAuthenticated, IsSuperuser]

    @extend_schema(
        parameters=[
            OpenApiParameter("is_active", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
        ],
        tags=["CRM"],
    )
    def list(self, request: Request, *args: str, **kwargs: str) -> Response:
        return super().list(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[PhoneEndpoint]:
        queryset = PhoneEndpoint.objects.select_related("staff").order_by(
            "endpoint_type",
            "label",
        )
        is_active = _query_bool(self.request.query_params.get("is_active"), "is_active")
        if is_active is None:
            return queryset
        return queryset.filter(is_active=is_active)

    def perform_create(self, serializer: PhoneEndpointSerializer) -> None:
        endpoint = serializer.save()
        rematch_phone_calls_task.delay([endpoint.normalized_number])

    def perform_update(self, serializer: PhoneEndpointSerializer) -> None:
        old_endpoint = self.get_object()
        old_number = old_endpoint.normalized_number
        endpoint = serializer.save()
        rematch_phone_calls_task.delay([old_number, endpoint.normalized_number])

    def perform_destroy(self, instance: PhoneEndpoint) -> None:
        number = instance.normalized_number
        instance.delete()
        rematch_phone_calls_task.delay([number])


class PhoneProviderSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    @extend_schema(
        operation_id="getPhoneProviderSettings",
        responses={200: PhoneProviderSettingsSerializer},
        tags=["CRM"],
    )
    def get(self, request: Request) -> Response:
        phone_settings = PhoneProviderSettings.get_solo()
        return Response(PhoneProviderSettingsSerializer(phone_settings).data)

    @extend_schema(
        operation_id="updatePhoneProviderSettings",
        request=PhoneProviderSettingsSerializer,
        responses={200: PhoneProviderSettingsSerializer},
        tags=["CRM"],
    )
    def patch(self, request: Request) -> Response:
        phone_settings = PhoneProviderSettings.get_solo()
        serializer = PhoneProviderSettingsSerializer(
            phone_settings,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
