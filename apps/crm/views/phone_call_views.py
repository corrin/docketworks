import mimetypes

from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
)
from apps.crm.serializers import (
    PhoneCallJobLinkSerializer,
    PhoneCallRecordingSerializer,
    PhoneCallRecordSerializer,
    PhoneNumberAssignmentSerializer,
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
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error


class PhoneCallRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PhoneCallRecordSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        parameters=[
            OpenApiParameter("client", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("contact", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("job", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
        tags=["CRM"],
    )
    def list(self, request, *args, **kwargs):
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

    def get_queryset(self):
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
        client_id = self.request.query_params.get("client")
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        contact_id = self.request.query_params.get("contact")
        if contact_id:
            queryset = queryset.filter(contact_id=contact_id)
        job_id = self.request.query_params.get("job")
        if job_id:
            queryset = queryset.filter(job_id=job_id)
        limit = self.request.query_params.get("limit")
        if not limit:
            return queryset

        try:
            parsed_limit = int(limit)
        except ValueError as exc:
            raise ValidationError({"limit": "Limit must be an integer"}) from exc

        if parsed_limit < 1 or parsed_limit > 100:
            raise ValidationError({"limit": "Limit must be between 1 and 100"})

        queryset = queryset[:parsed_limit]
        return queryset

    @extend_schema(
        operation_id="linkPhoneCallJob",
        request=PhoneCallJobLinkSerializer,
        responses={200: PhoneCallRecordSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="job-link")
    def link_job(self, request, pk=None):
        serializer = PhoneCallJobLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            call = link_phone_call_to_job(
                call_id=str(pk),
                job_id=str(serializer.validated_data["job"]),
                linked_by=request.user,
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
    def unlink_job(self, request, pk=None):
        try:
            call = unlink_phone_call_job(call_id=str(pk))
            response_serializer = self.get_serializer(call)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc

    @extend_schema(
        operation_id="assignPhoneCallNumber",
        request=PhoneNumberAssignmentSerializer,
        responses={200: PhoneNumberAssignmentSerializer},
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="assign-number")
    def assign_number(self, request):
        serializer = PhoneNumberAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            method = assign_phone_number(
                phone_number=serializer.validated_data["phone_number"],
                client_id=str(serializer.validated_data["client"]),
                contact_id=(
                    str(serializer.validated_data["contact"])
                    if serializer.validated_data.get("contact")
                    else None
                ),
                label=serializer.validated_data.get("label", ""),
                is_primary=serializer.validated_data.get("is_primary", False),
            )
            return Response(
                {
                    "phone_number": method.value,
                    "client": method.client_id or method.contact.client_id,
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


class PhoneCallRecordingViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PhoneCallRecordingSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    def get_queryset(self):
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
    def download(self, request, pk=None):
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
    def delete_local_file(self, request, pk=None):
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
    def delete_provider_file(self, request, pk=None):
        recording = get_object_or_404(self.get_queryset(), pk=pk)
        try:
            provider_delete_recording(recording)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            app_error = persist_app_error(exc)
            raise AlreadyLoggedException(exc, app_error.id) from exc
