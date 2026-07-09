from typing import TYPE_CHECKING, Any, TypedDict

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.company.models import ContactMethod
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)
from apps.crm.services.phone_call_service import (
    normalize_phone,
)

if TYPE_CHECKING:
    from apps.accounts.models import Staff


class PhoneCallJobLinkSerializer(serializers.Serializer[None]):
    """Request body for linking a phone call to a job."""

    job = serializers.UUIDField()


class PhoneNumberAssignmentSerializer(serializers.Serializer[None]):
    """Request body for assigning a call's external number to a company."""

    company = serializers.UUIDField()
    person = serializers.UUIDField(required=False, allow_null=True, default=None)
    is_primary = serializers.BooleanField(required=False, default=False)

    def get_fields(self) -> dict[str, "serializers.Field[Any, Any, Any, Any]"]:
        """Add the ``label`` body field.

        Declared here rather than as a class attribute because an attribute
        named ``label`` would shadow ``Field.label`` (the display string) on
        the serializer class itself. The ``Any`` parameters mirror the DRF
        stubs' own ``get_fields`` contract (a heterogeneous field mapping).
        """
        fields = super().get_fields()
        fields["label"] = serializers.CharField(
            max_length=255,
            required=False,
            allow_blank=True,
            default="",
        )
        return fields


def _recording_download_url(recording: PhoneCallRecording) -> str | None:
    if not recording.storage_path:
        return None
    return f"/api/crm/phone-call-recordings/{recording.id}/download/"


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

    def validate(self, attrs: "PhoneEndpointAttrs") -> "PhoneEndpointAttrs":
        """Reject an active endpoint over a number a company already owns.

        Mirrors PhoneEndpoint.save() so the API returns a clean 400 instead of
        a 500. Grandfathering symmetry: only enforced on create or when the
        number/is_active association changes.
        """
        if "number" in attrs:
            number = attrs["number"]
        elif self.instance is not None:
            number = self.instance.number
        else:
            number = ""
        normalized = normalize_phone(number)

        if "is_active" in attrs:
            is_active = attrs["is_active"]
        elif self.instance is not None:
            is_active = self.instance.is_active
        else:
            is_active = True  # model field default

        if self.instance is not None and (
            normalized == self.instance.normalized_number
            and is_active == self.instance.is_active
        ):
            return attrs  # association unchanged — grandfathered, like save()

        if is_active:
            conflict = ContactMethod.conflicting_company(normalized, set())
            if conflict:
                raise serializers.ValidationError(
                    {
                        "number": [
                            f"Phone number {normalized} already belongs to "
                            f"{conflict.owner_display_name()} and cannot be an "
                            "active internal phone endpoint."
                        ]
                    }
                )
        return attrs


class PhoneEndpointAttrs(TypedDict, total=False):
    """Writable fields accepted by ``PhoneEndpointSerializer.validate``."""

    number: str
    label: str
    endpoint_type: str
    staff: "Staff | None"
    provider_account_code: str
    provider_metadata: dict[str, object]
    is_active: bool


class PhoneProviderSettingsAttrs(TypedDict, total=False):
    """Writable fields accepted by ``PhoneProviderSettingsSerializer.validate``."""

    downloads_enabled: bool
    recording_deletion_enabled: bool
    base_url: str | None
    username: str
    password: str
    account_code: str


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

    def validate(self, attrs: PhoneProviderSettingsAttrs) -> PhoneProviderSettingsAttrs:
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


class PhoneCallRecordSerializer(serializers.ModelSerializer[PhoneCallRecord]):

    recording = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    person_name = serializers.SerializerMethodField()
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
            "company",
            "company_name",
            "person",
            "person_name",
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

    def get_company_name(self, obj: PhoneCallRecord) -> str:
        return obj.company.name if obj.company else ""

    def get_person_name(self, obj: PhoneCallRecord) -> str:
        return obj.person.name if obj.person else ""

    def get_origin_endpoint_label(self, obj: PhoneCallRecord) -> str:
        return obj.origin_endpoint.label if obj.origin_endpoint else ""

    def get_destination_endpoint_label(self, obj: PhoneCallRecord) -> str:
        return obj.destination_endpoint.label if obj.destination_endpoint else ""

    @extend_schema_field(PhoneCallRecordingSerializer(allow_null=True))
    def get_recording(self, obj: PhoneCallRecord) -> dict[str, object] | None:
        recordings_by_call_id = self.context.get("phone_recordings_by_call_id")
        if not isinstance(recordings_by_call_id, dict):
            try:
                recording = obj.recording
            except PhoneCallRecording.DoesNotExist:
                return None

            return PhoneCallRecordingSerializer(recording).data

        cached_recording = recordings_by_call_id.get(obj.id)
        if cached_recording is None:
            return None
        if not isinstance(cached_recording, PhoneCallRecording):
            raise TypeError("Recording cache contained an invalid value")

        return PhoneCallRecordingSerializer(cached_recording).data

    def get_job_number(self, obj: PhoneCallRecord) -> int | None:
        return obj.job.job_number if obj.job else None

    def get_job_name(self, obj: PhoneCallRecord) -> str:
        return obj.job.name if obj.job else ""

    def get_job_status(self, obj: PhoneCallRecord) -> str:
        return obj.job.status if obj.job else ""
