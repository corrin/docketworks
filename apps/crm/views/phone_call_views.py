import mimetypes
from uuid import UUID

from django.db.models import Q, QuerySet
from django.http import FileResponse
from django.shortcuts import get_object_or_404
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

from apps.accounts.models import Staff
from apps.client.models import ClientContactMethod
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
)
from apps.crm.serializers import (
    PhoneCallJobLinkPayload,
    PhoneCallRecordingSerializer,
    PhoneCallRecordSerializer,
    PhoneNumberAssignmentPayload,
)
from apps.crm.services.phone_call_service import (
    assign_phone_number,
    delete_local_recording,
    link_phone_call_to_job,
    provider_delete_recording,
    recording_file_path,
    unlink_phone_call_job,
)
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
        "phone_number": serializers.CharField(max_length=150),
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
    )
    filter_kwargs: dict[str, UUID] = {}
    for lookup, value in query_filters:
        if value is None:
            continue
        filter_kwargs[lookup] = value
    return filter_kwargs


def _assigned_phone_client_id(method: ClientContactMethod) -> UUID:
    client_id = method.client_id
    if client_id is not None:
        return client_id

    contact = method.contact
    if contact is None:
        raise RuntimeError("Assigned phone method has no owner")
    return contact.client_id


class PhoneCallRecordViewSet(viewsets.ReadOnlyModelViewSet[PhoneCallRecord]):
    serializer_class = PhoneCallRecordSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]
    pagination_class = PageSizePagination

    @extend_schema(
        parameters=[
            OpenApiParameter("client", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("contact", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("job", OpenApiTypes.UUID, OpenApiParameter.QUERY),
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
            )
            .filter(Q(origin__gt="") | Q(destination__gt=""))
            .order_by("-call_datetime")
        )
        return queryset.filter(**_phone_call_filter_kwargs(self.request))

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
        responses={200: PHONE_NUMBER_ASSIGNMENT_SCHEMA},
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="assign-number")
    def assign_number(self, request: Request) -> Response:
        try:
            payload = PhoneNumberAssignmentPayload.model_validate(request.data)
        except PydanticValidationError as exc:
            raise ValidationError(_validation_error_detail(exc.errors())) from exc
        try:
            method = assign_phone_number(
                phone_number=payload.phone_number,
                client_id=str(payload.client),
                contact_id=str(payload.contact) if payload.contact else None,
                label=payload.label,
                is_primary=payload.is_primary,
            )
            return Response(
                {
                    "phone_number": method.value,
                    "client": _assigned_phone_client_id(method),
                    "contact": method.contact_id,
                    "label": method.label,
                    "is_primary": method.is_primary,
                },
                status=status.HTTP_200_OK,
            )
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc


class PhoneCallRecordingViewSet(viewsets.ReadOnlyModelViewSet[PhoneCallRecording]):
    serializer_class = PhoneCallRecordingSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    def get_queryset(self) -> QuerySet[PhoneCallRecording]:
        return PhoneCallRecording.objects.select_related(
            "call",
            "call__client",
            "call__contact",
        ).order_by("-call__call_datetime")

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
