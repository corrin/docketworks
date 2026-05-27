from uuid import UUID

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsOfficeStaff
from apps.workflow.models import AppError
from apps.workflow.models.session_replay import SessionReplayRecording
from apps.workflow.serializers import (
    SessionReplayChunkCreateSerializer,
    SessionReplayChunkSerializer,
    SessionReplayEventsResponseSerializer,
    SessionReplayFrontendErrorResponseSerializer,
    SessionReplayFrontendErrorSerializer,
    SessionReplayListResponseSerializer,
    SessionReplayRecordingCreateSerializer,
    SessionReplayRecordingSerializer,
)
from apps.workflow.services.session_replay_service import (
    append_chunk,
    create_recording,
    list_recordings,
    recording_events,
)
from apps.workflow.utils import parse_pagination_params


def _parse_uuid_param(value: str | None, field: str) -> str | None:
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"Invalid {field} parameter") from exc


class SessionReplayRecordingListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="session_replay_recordings_list",
        request=None,
        responses={200: SessionReplayListResponseSerializer},
        parameters=[
            OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("offset", int, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("user_id", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter("job_id", str, OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                "started_after", str, OpenApiParameter.QUERY, required=False
            ),
            OpenApiParameter(
                "started_before", str, OpenApiParameter.QUERY, required=False
            ),
        ],
    )
    def get(self, request):
        if not IsOfficeStaff().has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            limit, offset = parse_pagination_params(request)
            user_id = _parse_uuid_param(request.query_params.get("user_id"), "user_id")
            job_id = _parse_uuid_param(request.query_params.get("job_id"), "job_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = list_recordings(
            limit=limit,
            offset=offset,
            user_id=user_id,
            job_id=job_id,
            started_after=request.query_params.get("started_after"),
            started_before=request.query_params.get("started_before"),
        )
        serializer = SessionReplayListResponseSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="session_replay_recordings_create",
        request=SessionReplayRecordingCreateSerializer,
        responses={201: SessionReplayRecordingSerializer},
    )
    def post(self, request):
        serializer = SessionReplayRecordingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recording = create_recording(
            user=request.user,
            user_agent=request.headers.get("User-Agent", ""),
            **serializer.validated_data,
        )
        return Response(
            SessionReplayRecordingSerializer(recording).data,
            status=status.HTTP_201_CREATED,
        )


class SessionReplayRecordingDetailView(APIView):
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        operation_id="session_replay_recordings_retrieve",
        responses={200: SessionReplayRecordingSerializer},
    )
    def get(self, request, pk):
        recording = get_object_or_404(
            SessionReplayRecording.objects.select_related("user"), pk=pk
        )
        return Response(SessionReplayRecordingSerializer(recording).data)


class SessionReplayChunkCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="session_replay_recording_chunks_create",
        request=SessionReplayChunkCreateSerializer,
        responses={201: SessionReplayChunkSerializer},
    )
    def post(self, request, pk):
        recording = get_object_or_404(SessionReplayRecording, pk=pk, user=request.user)
        serializer = SessionReplayChunkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            chunk = append_chunk(recording=recording, **serializer.validated_data)
        except IntegrityError:
            return Response(
                {"error": "Duplicate replay chunk sequence"},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            SessionReplayChunkSerializer(chunk).data,
            status=status.HTTP_201_CREATED,
        )


class SessionReplayEventsView(APIView):
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        operation_id="session_replay_recording_events_retrieve",
        responses={200: SessionReplayEventsResponseSerializer},
    )
    def get(self, request, pk):
        recording = get_object_or_404(
            SessionReplayRecording.objects.select_related("user"), pk=pk
        )
        payload = {
            "recording": recording,
            "events": recording_events(recording),
        }
        return Response(SessionReplayEventsResponseSerializer(payload).data)


class SessionReplayFrontendErrorView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="session_replay_frontend_errors_create",
        request=SessionReplayFrontendErrorSerializer,
        responses={201: SessionReplayFrontendErrorResponseSerializer},
    )
    def post(self, request):
        serializer = SessionReplayFrontendErrorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        replay_id = data.get("session_replay_id")
        error = AppError.objects.create(
            message=data["message"],
            data={
                "trace": data.get("stack") or "",
                "path": data["path"],
                "component": data.get("component") or "",
                "source": "frontend",
            },
            app="frontend",
            file=data.get("file") or "",
            function=data.get("function") or "",
            user_id=request.user.id,
            session_replay_id=replay_id,
        )
        return Response({"id": str(error.id)}, status=status.HTTP_201_CREATED)
