"""Request and response schemas for the CRM phone-call API.

Provider-settings credentials are write-only and surface only as
``has_username`` and ``has_password`` booleans; stored values never cross the
read boundary.
"""

from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from ninja import Field, Schema
from pydantic import StringConstraints

from apps.core.schemas import ResponseSchema, omittable
from apps.crm.models import (
    PhoneCallRecord,
    PhoneCallRecording,
    PhoneEndpoint,
    PhoneProviderSettings,
)

EndpointTypeLiteral = Literal["main_line", "staff_mobile", "staff_ddi", "extension", "shared"]


class OperationErrorOut(ResponseSchema):
    """Wire contract for OperationErrorOut."""

    status: Literal["error"] = "error"
    message: str


class PhoneCallRecordingOut(Schema):
    """Wire contract for PhoneCallRecordingOut."""

    id: UUID
    provider_recording_id: str
    account_code: str
    filename: str | None
    content_type: str | None
    byte_size: int | None
    sha256: str | None
    archived_at: datetime | None
    archive_error: str | None
    provider_deleted_at: datetime | None
    provider_delete_error: str | None
    local_deleted_at: datetime | None
    download_url: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_recording(cls, recording: PhoneCallRecording) -> "PhoneCallRecordingOut":
        """Build the payload from the model row.

        Built explicitly (not a resolver) because ninja re-validates returned
        schema instances, and a resolver would then run against the schema
        object, which has no storage_path.
        """
        # Same-origin relative URL; absolute links break proxied deployments.
        download_url = (
            f"/api/crm/phone-call-recordings/{recording.id}/download/"
            if recording.storage_path
            else None
        )
        return cls(
            id=recording.id,
            provider_recording_id=recording.provider_recording_id,
            account_code=recording.account_code,
            filename=recording.filename,
            content_type=recording.content_type,
            byte_size=recording.byte_size,
            sha256=recording.sha256,
            archived_at=recording.archived_at,
            archive_error=recording.archive_error,
            provider_deleted_at=recording.provider_deleted_at,
            provider_delete_error=recording.provider_delete_error,
            local_deleted_at=recording.local_deleted_at,
            download_url=download_url,
            created_at=recording.created_at,
            updated_at=recording.updated_at,
        )


class PhoneCallRecordOut(Schema):
    """Wire contract for PhoneCallRecordOut."""

    id: UUID
    provider_call_id: str
    account_code: str
    call_datetime: datetime
    call_date: date
    call_time: time
    call_type: str | None
    status: str | None
    description: str | None
    origin: str | None
    destination: str | None
    direction: str
    our_number: str | None
    external_number: str | None
    origin_endpoint: UUID | None
    origin_endpoint_label: str
    destination_endpoint: UUID | None
    destination_endpoint_label: str
    duration_seconds: int
    charge: float | None
    company: UUID | None
    company_name: str
    person: UUID | None
    person_name: str
    job: UUID | None
    job_number: int | None
    job_name: str
    job_status: str
    job_linked_at: datetime | None
    job_linked_by: UUID | None
    recording: PhoneCallRecordingOut | None
    imported_at: datetime
    updated_at: datetime

    @classmethod
    def from_call(
        cls,
        call: PhoneCallRecord,
        recording: PhoneCallRecording | None,
    ) -> "PhoneCallRecordOut":
        """Build the payload from a call row and its (optional) recording."""
        return cls(
            id=call.id,
            provider_call_id=call.provider_call_id,
            account_code=call.account_code,
            call_datetime=call.call_datetime,
            call_date=call.call_date,
            call_time=call.call_time,
            call_type=call.call_type,
            status=call.status,
            description=call.description,
            origin=call.origin,
            destination=call.destination,
            direction=call.direction,
            our_number=call.our_number,
            external_number=call.external_number,
            origin_endpoint=call.origin_endpoint_id,
            origin_endpoint_label=call.origin_endpoint.label if call.origin_endpoint else "",
            destination_endpoint=call.destination_endpoint_id,
            destination_endpoint_label=(
                call.destination_endpoint.label if call.destination_endpoint else ""
            ),
            duration_seconds=call.duration_seconds,
            charge=float(call.charge) if call.charge is not None else None,
            company=call.company_id,
            company_name=call.company.name if call.company else "",
            person=call.person_id,
            person_name=call.person.name if call.person else "",
            job=call.job_id,
            job_number=call.job.job_number if call.job else None,
            job_name=call.job.name if call.job else "",
            job_status=call.job.status if call.job else "",
            job_linked_at=call.job_linked_at,
            job_linked_by=call.job_linked_by_id,
            recording=(PhoneCallRecordingOut.from_recording(recording) if recording else None),
            imported_at=call.imported_at,
            updated_at=call.updated_at,
        )


class PaginatedPhoneCallRecordsOut(Schema):
    """Wire contract for PaginatedPhoneCallRecordsOut."""

    results: list[PhoneCallRecordOut]
    count: int
    page: int
    page_size: int
    total_pages: int


class PhoneCallListFilters(Schema):
    """Query parameters for the phone-call listing endpoint."""

    company: UUID | None = None
    person: UUID | None = None
    job: UUID | None = None
    origin_endpoint: UUID | None = None
    destination_endpoint: UUID | None = None
    company_match: Literal["all", "matched", "unmatched"] = "all"
    job_link: Literal["all", "linked", "unlinked"] = "all"
    direction: Literal["all", "inbound", "outbound", "internal", "unknown"] = "all"
    has_recording: bool | None = None
    from_date: date | None = None
    to_date: date | None = None
    q: str | None = None
    page: int = 1
    page_size: int | None = None


class PhoneCallJobLinkIn(Schema):
    """Request body for linking a phone call to a job."""

    job: UUID


class PhoneNumberAssignmentIn(Schema):
    """Request body for assigning a call's external number to a company."""

    company: UUID
    person: UUID | None = None
    is_primary: bool = False
    label: str = Field("", max_length=255)


class PhoneEndpointOut(Schema):
    """Wire contract for PhoneEndpointOut."""

    id: UUID
    number: str
    normalized_number: str
    label: str
    endpoint_type: str
    staff: UUID | None
    staff_name: str
    provider_account_code: str | None
    provider_metadata: dict[str, object]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_staff(obj: PhoneEndpoint) -> UUID | None:
        """Return the staff foreign-key id rather than a nested object."""
        return obj.staff_id

    @staticmethod
    def resolve_staff_name(obj: PhoneEndpoint) -> str:
        """Return the staff display name, or an empty string when unassigned."""
        if not obj.staff:
            return ""
        return obj.staff.get_display_name()


class PhoneEndpointCreateIn(Schema):
    """Wire contract for PhoneEndpointCreateIn."""

    number: str = Field(min_length=1, max_length=150)
    label: str = Field(min_length=1, max_length=255)
    endpoint_type: EndpointTypeLiteral
    staff: UUID | None = None
    provider_account_code: str | None = Field(None, min_length=1, max_length=100)
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    is_active: bool = True


class PhoneEndpointPutIn(Schema):
    """Wire contract for PhoneEndpointPutIn."""

    number: str = Field(min_length=1, max_length=150)
    label: str = Field(min_length=1, max_length=255)
    endpoint_type: EndpointTypeLiteral
    staff: UUID | None = None
    provider_account_code: str | None = Field(None, min_length=1, max_length=100)
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    is_active: bool = True


class PhoneEndpointPatchIn(Schema):
    """Wire contract for PhoneEndpointPatchIn."""

    # Every default here is a presence marker, never a value: the handler reads
    # `exclude_unset` and falls back to the stored row. Publishing them said
    # "omit this and you get ''" — a value the same field's min_length rejects.
    # omittable() keeps them optional and drops the default from the schema,
    # which is also what v1 emits (a bare {"type": "boolean"}, no default).
    number: Annotated[str, StringConstraints(min_length=1, max_length=150)] = omittable("")
    label: Annotated[str, StringConstraints(min_length=1, max_length=255)] = omittable("")
    endpoint_type: EndpointTypeLiteral = omittable("main_line")
    staff: UUID | None = None
    provider_account_code: str | None = Field(None, min_length=1, max_length=100)
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    is_active: bool = omittable(True)


class PhoneProviderSettingsOut(Schema):
    """Wire contract for PhoneProviderSettingsOut."""

    id: int
    downloads_enabled: bool
    recording_deletion_enabled: bool
    base_url: str | None
    has_username: bool
    has_password: bool
    account_code: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_has_username(obj: PhoneProviderSettings) -> bool:
        """Report whether a username is stored (the value never leaves the server)."""
        return bool(obj.username)

    @staticmethod
    def resolve_has_password(obj: PhoneProviderSettings) -> bool:
        """Report whether a password is stored (the value never leaves the server)."""
        return bool(obj.password)


class PhoneProviderSettingsPatchIn(Schema):
    """Wire contract for PhoneProviderSettingsPatchIn."""

    # As above: presence markers, not values. `provided.get(key, stored_value)`
    # in the handler means an omitted flag keeps the stored setting, so the
    # published `default: false` actively misdescribed the behaviour.
    downloads_enabled: bool = omittable(False)
    recording_deletion_enabled: bool = omittable(False)
    base_url: str | None = Field(None, min_length=1, max_length=200)
    username: Annotated[str, StringConstraints(min_length=1)] = omittable("")
    password: Annotated[str, StringConstraints(min_length=1)] = omittable("")
    account_code: str | None = Field(None, min_length=1, max_length=100)
