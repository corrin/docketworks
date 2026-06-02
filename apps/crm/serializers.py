from rest_framework import serializers

from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneNumberClientMapping,
)
from apps.crm.services.phone_call_service import call_parties, normalize_mapping


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
    recording = PhoneCallRecordingSerializer(read_only=True, allow_null=True)
    client_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()
    direction = serializers.SerializerMethodField()
    our_number = serializers.SerializerMethodField()
    external_number = serializers.SerializerMethodField()

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
            "recording",
            "imported_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_direction(self, obj: PhoneCallRecord) -> str:
        return call_parties(obj)["direction"]

    def get_our_number(self, obj: PhoneCallRecord) -> str:
        return call_parties(obj)["our_number"]

    def get_external_number(self, obj: PhoneCallRecord) -> str:
        return call_parties(obj)["external_number"]

    def get_client_name(self, obj: PhoneCallRecord) -> str:
        return obj.client.name if obj.client else ""

    def get_contact_name(self, obj: PhoneCallRecord) -> str:
        return obj.contact.name if obj.contact else ""


class PhoneNumberClientMappingSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()

    class Meta:
        model = PhoneNumberClientMapping
        fields = (
            "id",
            "phone_number",
            "client",
            "client_name",
            "contact",
            "contact_name",
            "label",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "client_name",
            "contact_name",
            "created_at",
            "updated_at",
        )

    def get_client_name(self, obj: PhoneNumberClientMapping) -> str:
        return obj.client.name

    def get_contact_name(self, obj: PhoneNumberClientMapping) -> str:
        return obj.contact.name if obj.contact else ""

    def validate(self, attrs):
        instance = self.instance or PhoneNumberClientMapping()
        for key, value in attrs.items():
            setattr(instance, key, value)
        normalize_mapping(instance)
        attrs["phone_number"] = instance.phone_number
        return attrs
