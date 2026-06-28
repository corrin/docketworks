from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
)
from apps.crm.services.phone_call_service import (
    call_parties,
    configured_own_numbers,
    normalize_phone,
)


class PhoneCallRecordingSerializer(serializers.ModelSerializer):
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
        if not obj.storage_path:
            return None
        request = self.context.get("request") if self.context else None
        path = f"/api/crm/phone-call-recordings/{obj.id}/download/"
        if request:
            return request.build_absolute_uri(path)
        return path


class PhoneCallRecordSerializer(serializers.ModelSerializer):
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
        cache_key = "_phone_own_numbers"
        if cache_key not in self.context:
            self.context[cache_key] = configured_own_numbers()
        return self.context[cache_key]

    def _call_parties(self, obj: PhoneCallRecord) -> dict[str, str]:
        cache_key = "_phone_call_parties"
        if cache_key not in self.context:
            self.context[cache_key] = {}
        cached_parties = self.context[cache_key]
        if obj.id not in cached_parties:
            cached_parties[obj.id] = call_parties(obj, self._own_numbers())
        return cached_parties[obj.id]

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
    def get_recording(self, obj: PhoneCallRecord) -> dict[str, Any] | None:
        recordings_by_call_id = self.context.get("phone_recordings_by_call_id")
        if isinstance(recordings_by_call_id, dict):
            recording = recordings_by_call_id.get(obj.id)
            if recording is None:
                return None
            return dict(
                PhoneCallRecordingSerializer(
                    recording,
                    context=self.context,
                ).data
            )

        prefetched = getattr(obj, "_prefetched_recording", None)
        if isinstance(prefetched, list):
            recording = prefetched[0] if prefetched else None
        else:
            recording = prefetched
        if recording is None:
            if getattr(obj, "_has_recording", True) is False:
                return None
            try:
                recording = obj.recording
            except PhoneCallRecording.DoesNotExist:
                return None
        return dict(
            PhoneCallRecordingSerializer(
                recording,
                context=self.context,
            ).data
        )

    def get_job_number(self, obj: PhoneCallRecord) -> int | None:
        return obj.job.job_number if obj.job else None

    def get_job_name(self, obj: PhoneCallRecord) -> str:
        return obj.job.name if obj.job else ""

    def get_job_status(self, obj: PhoneCallRecord) -> str:
        return obj.job.status if obj.job else ""


class PhoneCallJobLinkSerializer(serializers.Serializer):
    job = serializers.UUIDField()


class PhoneNumberAssignmentSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=150)
    client = serializers.UUIDField()
    contact = serializers.UUIDField(required=False, allow_null=True)
    label = serializers.CharField(max_length=255, required=False, allow_blank=True)
    is_primary = serializers.BooleanField(required=False, default=False)

    def validate_phone_number(self, value: str) -> str:
        normalized = normalize_phone(value)
        if not normalized:
            raise serializers.ValidationError("Phone number is required")
        return value.strip()
