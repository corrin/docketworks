from datetime import datetime
from typing import TypedDict
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from pydantic import BaseModel, ConfigDict
from rest_framework import serializers

from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.crm.services.phone_call_service import (
    normalize_phone,
)


class PhoneCallPayloadModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class PhoneCallJobLinkPayload(PhoneCallPayloadModel):
    job: UUID


class PhoneNumberAssignmentPayload(PhoneCallPayloadModel):
    client: UUID
    contact: UUID | None = None
    label: str = ""
    is_primary: bool = False


class PhoneCallRecordingResponse(TypedDict):
    id: str
    provider_recording_id: str
    account_code: str
    filename: str
    content_type: str
    byte_size: int | None
    sha256: str
    archived_at: str | None
    archive_error: str
    provider_deleted_at: str | None
    provider_delete_error: str
    local_deleted_at: str | None
    download_url: str | None
    created_at: str
    updated_at: str


def _datetime_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _recording_download_url(recording: PhoneCallRecording) -> str | None:
    if not recording.storage_path:
        return None
    return f"/api/crm/phone-call-recordings/{recording.id}/download/"


def _recording_response(recording: PhoneCallRecording) -> PhoneCallRecordingResponse:
    return {
        "id": str(recording.id),
        "provider_recording_id": recording.provider_recording_id,
        "account_code": recording.account_code,
        "filename": recording.filename,
        "content_type": recording.content_type,
        "byte_size": recording.byte_size,
        "sha256": recording.sha256,
        "archived_at": _datetime_value(recording.archived_at),
        "archive_error": recording.archive_error,
        "provider_deleted_at": _datetime_value(recording.provider_deleted_at),
        "provider_delete_error": recording.provider_delete_error,
        "local_deleted_at": _datetime_value(recording.local_deleted_at),
        "download_url": _recording_download_url(recording),
        "created_at": recording.created_at.isoformat(),
        "updated_at": recording.updated_at.isoformat(),
    }


class PhoneCallRecordingSerializer(serializers.ModelSerializer[PhoneCallRecording]):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = PhoneCallRecording
        fields = (
            "id",
            "provider_recording_id",
            "account_code",
            "filename",
            "content_type",
            "byte_size",
            "sha256",
            "archived_at",
            "archive_error",
            "provider_deleted_at",
            "provider_delete_error",
            "local_deleted_at",
            "download_url",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_download_url(self, obj: PhoneCallRecording) -> str | None:
        return _recording_download_url(obj)


class PhoneEndpointSerializer(serializers.ModelSerializer[PhoneEndpoint]):
    staff_name = serializers.SerializerMethodField()

    class Meta:
        model = PhoneEndpoint
        fields = (
            "id",
            "number",
            "normalized_number",
            "label",
            "endpoint_type",
            "staff",
            "staff_name",
            "provider_account_code",
            "provider_metadata",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "normalized_number",
            "staff_name",
            "created_at",
            "updated_at",
        )

    def get_staff_name(self, obj: PhoneEndpoint) -> str:
        if not obj.staff:
            return ""
        return obj.staff.get_display_name()

    def validate_number(self, value: str) -> str:
        normalized = normalize_phone(value)
        if not normalized:
            raise serializers.ValidationError("Phone endpoint requires a number.")
        return value.strip()


class PhoneProviderSettingsSerializer(
    serializers.ModelSerializer[PhoneProviderSettings]
):
    has_username = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()
    username = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )

    class Meta:
        model = PhoneProviderSettings
        fields = (
            "id",
            "downloads_enabled",
            "recording_deletion_enabled",
            "base_url",
            "has_username",
            "username",
            "has_password",
            "password",
            "account_code",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs: dict) -> dict:
        downloads_enabled = attrs.get(
            "downloads_enabled",
            getattr(self.instance, "downloads_enabled", False),
        )
        base_url = attrs.get("base_url", getattr(self.instance, "base_url", None))
        if downloads_enabled and not base_url:
            raise serializers.ValidationError(
                {"base_url": "Base URL is required when phone downloads are enabled."}
            )
        return attrs

    def get_has_username(self, obj: PhoneProviderSettings) -> bool:
        return bool(obj.username)

    def get_has_password(self, obj: PhoneProviderSettings) -> bool:
        return bool(obj.password)

    def to_representation(self, instance: PhoneProviderSettings) -> dict:
        data = super().to_representation(instance)
        data["has_username"] = bool(instance.username)
        data["has_password"] = bool(instance.password)
        return data


class PhoneCallRecordSerializer(serializers.ModelSerializer[PhoneCallRecord]):

    recording = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    origin_endpoint_label = serializers.SerializerMethodField()
    destination_endpoint_label = serializers.SerializerMethodField()
    job_number = serializers.SerializerMethodField()
    job_name = serializers.SerializerMethodField()
    job_status = serializers.SerializerMethodField()

    class Meta:
        model = PhoneCallRecord
        fields = (
            "id",
            "provider_call_id",
            "account_code",
            "call_datetime",
            "call_date",
            "call_time",
            "call_type",
            "status",
            "description",
            "origin",
            "destination",
            "direction",
            "our_number",
            "external_number",
            "origin_endpoint",
            "origin_endpoint_label",
            "destination_endpoint",
            "destination_endpoint_label",
            "duration_seconds",
            "charge",
            "client",
            "client_name",
            "contact",
            "contact_name",
            "job",
            "job_number",
            "job_name",
            "job_status",
            "job_linked_at",
            "job_linked_by",
            "recording",
            "imported_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_client_name(self, obj: PhoneCallRecord) -> str:
        return obj.client.name if obj.client else ""

    def get_contact_name(self, obj: PhoneCallRecord) -> str:
        return obj.contact.name if obj.contact else ""

    def get_origin_endpoint_label(self, obj: PhoneCallRecord) -> str:
        return obj.origin_endpoint.label if obj.origin_endpoint else ""

    def get_destination_endpoint_label(self, obj: PhoneCallRecord) -> str:
        return obj.destination_endpoint.label if obj.destination_endpoint else ""

    @extend_schema_field(PhoneCallRecordingSerializer(allow_null=True))
    def get_recording(self, obj: PhoneCallRecord) -> PhoneCallRecordingResponse | None:
        recordings_by_call_id = self.context.get("phone_recordings_by_call_id")
        if not isinstance(recordings_by_call_id, dict):
            try:
                recording = obj.recording
            except PhoneCallRecording.DoesNotExist:
                return None

            return _recording_response(recording)

        cached_recording = recordings_by_call_id.get(obj.id)
        if cached_recording is None:
            return None
        if not isinstance(cached_recording, PhoneCallRecording):
            raise TypeError("Recording cache contained an invalid value")

        return _recording_response(cached_recording)

    def get_job_number(self, obj: PhoneCallRecord) -> int | None:
        return obj.job.job_number if obj.job else None

    def get_job_name(self, obj: PhoneCallRecord) -> str:
        return obj.job.name if obj.job else ""

    def get_job_status(self, obj: PhoneCallRecord) -> str:
        return obj.job.status if obj.job else ""
