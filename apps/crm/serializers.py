from datetime import datetime
from typing import TypedDict
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from pydantic import BaseModel, ConfigDict, field_validator
from rest_framework import serializers
from rest_framework.request import Request

from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
)
from apps.crm.services.phone_call_service import (
    call_parties,
    configured_own_numbers,
    normalize_phone,
)


class PhoneCallPayloadModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class PhoneCallJobLinkPayload(PhoneCallPayloadModel):
    job: UUID


class PhoneNumberAssignmentPayload(PhoneCallPayloadModel):
    phone_number: str
    client: UUID
    contact: UUID | None = None
    label: str = ""
    is_primary: bool = False

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        normalized = normalize_phone(value)
        if not normalized:
            raise ValueError("Phone number is required")
        return value.strip()


class PhoneCallRecordingResponse(TypedDict):
    id: str
    provider_recording_id: str
    account_code: str
    filename: str
    storage_path: str
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


def _recording_download_url(
    recording: PhoneCallRecording,
    request: Request | None,
) -> str | None:
    if not recording.storage_path:
        return None
    path = f"/api/crm/phone-call-recordings/{recording.id}/download/"
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _recording_response(
    recording: PhoneCallRecording,
    request: Request | None,
) -> PhoneCallRecordingResponse:
    return {
        "id": str(recording.id),
        "provider_recording_id": recording.provider_recording_id,
        "account_code": recording.account_code,
        "filename": recording.filename,
        "storage_path": recording.storage_path,
        "content_type": recording.content_type,
        "byte_size": recording.byte_size,
        "sha256": recording.sha256,
        "archived_at": _datetime_value(recording.archived_at),
        "archive_error": recording.archive_error,
        "provider_deleted_at": _datetime_value(recording.provider_deleted_at),
        "provider_delete_error": recording.provider_delete_error,
        "local_deleted_at": _datetime_value(recording.local_deleted_at),
        "download_url": _recording_download_url(recording, request),
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
            "storage_path",
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
        request = self.context.get("request") if self.context else None
        if isinstance(request, Request):
            return _recording_download_url(obj, request)
        return _recording_download_url(obj, None)


class PhoneCallRecordSerializer(serializers.ModelSerializer[PhoneCallRecord]):
    _phone_own_numbers_cache: set[str] | None = None
    _phone_call_parties_cache: dict[UUID, dict[str, str]] | None = None

    recording = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    direction = serializers.SerializerMethodField()
    our_number = serializers.SerializerMethodField()
    external_number = serializers.SerializerMethodField()
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

    def _own_numbers(self) -> set[str]:
        cached_numbers = self._phone_own_numbers_cache
        if cached_numbers is not None:
            return cached_numbers

        own_numbers = configured_own_numbers()
        self._phone_own_numbers_cache = own_numbers
        return own_numbers

    def _call_parties(self, obj: PhoneCallRecord) -> dict[str, str]:
        cached_parties = self._phone_call_parties_cache
        if cached_parties is None:
            cached_parties = {}
            self._phone_call_parties_cache = cached_parties

        cached_party = cached_parties.get(obj.id)
        if cached_party is not None:
            return cached_party

        party = call_parties(obj, self._own_numbers())
        cached_parties[obj.id] = party
        return party

    def get_direction(self, obj: PhoneCallRecord) -> str:
        return self._call_parties(obj)["direction"]

    def get_our_number(self, obj: PhoneCallRecord) -> str:
        return self._call_parties(obj)["our_number"]

    def get_external_number(self, obj: PhoneCallRecord) -> str:
        return self._call_parties(obj)["external_number"]

    def get_client_name(self, obj: PhoneCallRecord) -> str:
        return obj.client.name if obj.client else ""

    def get_contact_name(self, obj: PhoneCallRecord) -> str:
        return obj.contact.name if obj.contact else ""

    @extend_schema_field(PhoneCallRecordingSerializer(allow_null=True))
    def get_recording(self, obj: PhoneCallRecord) -> PhoneCallRecordingResponse | None:
        request = self.context.get("request") if self.context else None
        typed_request = request if isinstance(request, Request) else None
        recordings_by_call_id = self.context.get("phone_recordings_by_call_id")
        if not isinstance(recordings_by_call_id, dict):
            try:
                recording = obj.recording
            except PhoneCallRecording.DoesNotExist:
                return None

            return _recording_response(recording, typed_request)

        cached_recording = recordings_by_call_id.get(obj.id)
        if cached_recording is None:
            return None
        if not isinstance(cached_recording, PhoneCallRecording):
            raise TypeError("Recording cache contained an invalid value")

        return _recording_response(cached_recording, typed_request)

    def get_job_number(self, obj: PhoneCallRecord) -> int | None:
        return obj.job.job_number if obj.job else None

    def get_job_name(self, obj: PhoneCallRecord) -> str:
        return obj.job.name if obj.job else ""

    def get_job_status(self, obj: PhoneCallRecord) -> str:
        return obj.job.status if obj.job else ""
