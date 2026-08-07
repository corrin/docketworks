"""Request and response schemas for the company and people endpoints.

Schemas here are pure shape declarations; payload building lives in the
service formatters (one implementation per concept, ADR 0039). Error responses
use the standard envelope from ADR 0013.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email as django_validate_email
from ninja import Schema
from pydantic import field_validator

from apps.company.models import ContactMethod, SupplierSearchAlias
from apps.core.schemas import NonBlankText, NullableText, omittable

MethodType = Literal["phone", "email"]
MethodSource = Literal["imported", "local"]


def clean_optional_email(value: str | None) -> str | None:
    """Validate an optional email while accepting null but not blank input.

    The ONE email-validation implementation (ADR 0039); purchasing reuses it
    for the PO email endpoint's recipient override. Django's validator defines
    the accepted address set.
    """
    if value is None:
        return None
    try:
        django_validate_email(value)
    except DjangoValidationError as exc:
        raise ValueError("Enter a valid email address.") from exc
    return value


def _require_phone_digits(value: str | None) -> str | None:
    """Reject phone values that normalize to no digits."""
    if value and not ContactMethod.normalize_phone(value):
        raise ValueError("Phone number must contain at least one digit")
    return value


# ── Companies ────────────────────────────────────────────────────────────


class CompanySearchQuery(Schema):
    """Query parameters for the company search endpoint."""

    q: str = ""
    page: int = 1
    page_size: int = 50
    sort_by: str = "name"
    sort_dir: str = "asc"


class ContactMethodListQuery(Schema):
    """Query params for companies_contact_methods_list."""

    company_id: UUID | None = None
    person_id: UUID | None = None
    method_type: str | None = None
    page: int = 1
    page_size: int | None = None


class CompanyNameOnly(Schema):
    """Wire contract for CompanyNameOnly."""

    id: UUID
    name: str


class CompanySearchResult(Schema):
    """Wire contract for CompanySearchResult."""

    id: str
    name: str
    email: str
    phone: str
    address: str
    is_account_customer: bool
    is_supplier: bool
    allow_jobs: bool
    xero_contact_id: str
    last_invoice_date: datetime | None
    total_spend: str


class CompanySearchResponse(Schema):
    """Wire contract for CompanySearchResponse."""

    results: list[CompanySearchResult]
    count: int
    page: int
    page_size: int
    total_pages: int


class CompanyDetailResponse(Schema):
    """Wire contract for CompanyDetailResponse."""

    id: str
    name: str
    email: str
    phone: str
    address: str
    is_account_customer: bool
    is_supplier: bool
    allow_jobs: bool
    xero_contact_id: str
    xero_tenant_id: str
    xero_last_modified: datetime
    xero_last_synced: datetime | None
    xero_archived: bool
    xero_merged_into_id: str
    merged_into: str | None
    django_created_at: datetime
    django_updated_at: datetime
    last_invoice_date: datetime | None
    total_spend: str


class CompanyCreateRequest(Schema):
    """Wire contract for CompanyCreateRequest."""

    name: str
    email: str | None = None
    # Stored as the company's primary ContactMethod, not a Company column
    phone: str | None = None
    address: str | None = None
    is_account_customer: bool = True
    allow_jobs: bool = True

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return clean_optional_email(value)


class CompanyCreateResponse(Schema):
    """Wire contract for CompanyCreateResponse."""

    success: bool
    company: CompanySearchResult
    message: str


class CompanyUpdateRequest(Schema):
    """Partial company update in which field presence is significant.

    ``phone`` upserts/clears the primary ContactMethod: supplied-and-blank
    clears it, omitted leaves methods untouched (use ``model_dump(
    exclude_unset=True)``).
    """

    # `email` and `phone` are nullable because null CLEARS them; the rest are
    # merely optional, and v1 declares them non-nullable. Spelling both as
    # `| None` is what made `{"name": null}` a silent 200 (ADR 0044).
    name: NonBlankText = omittable("")
    email: NullableText = None
    phone: str | None = None
    address: NonBlankText = omittable("")
    is_account_customer: bool = omittable(False)
    allow_jobs: bool = omittable(False)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return clean_optional_email(value)


class CompanyUpdateResponse(Schema):
    """Wire contract for CompanyUpdateResponse."""

    success: bool
    company: CompanyDetailResponse
    message: str


class CompanyJobCompanyRef(Schema):
    """Company reference embedded in a job header row."""

    id: str
    name: str


class CompanyJobHeader(Schema):
    """Wire contract for CompanyJobHeader."""

    job_id: UUID
    job_number: int
    name: str
    company: CompanyJobCompanyRef | None
    status: str
    pricing_methodology: str | None
    speed_quality_tradeoff: str
    fully_invoiced: bool
    has_quote_in_xero: bool
    is_fixed_price: bool
    quote_acceptance_date: datetime | None
    paid: bool
    rejected_flag: bool
    min_people: int
    max_people: int


class CompanyJobsResponse(Schema):
    """Wire contract for CompanyJobsResponse."""

    results: list[CompanyJobHeader]


# ── Company people (links) ───────────────────────────────────────────────


class CompanyPerson(Schema):
    """Wire contract for CompanyPerson."""

    person_id: UUID
    person_name: str
    person_email: str | None
    primary_phone: str
    position: str | None
    is_primary: bool
    notes: str | None


class CompanyPersonCreateRequest(Schema):
    """Wire contract for CompanyPersonCreateRequest."""

    name: str
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    notes: str | None = None
    is_primary: bool = False

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return clean_optional_email(value)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return _require_phone_digits(value)


class PersonCompanyLink(Schema):
    """Wire contract for PersonCompanyLink."""

    company_id: UUID
    company_name: str
    position: str | None
    is_primary: bool
    notes: str | None
    is_active: bool


class PhonePersonMatch(Schema):
    """Wire contract for PhonePersonMatch."""

    person_id: UUID
    person_name: str
    person_email: str | None
    company_links: list[PersonCompanyLink]


class PhoneCompanyOwner(Schema):
    """Wire contract for PhoneCompanyOwner."""

    company_id: UUID
    company_name: str


class PhoneOwnership(Schema):
    """Wire contract for PhoneOwnership."""

    status: Literal["available", "people", "company", "internal"]
    normalized_phone: str
    can_create_person: bool
    people: list[PhonePersonMatch]
    companies: list[PhoneCompanyOwner]


class PhoneOwnershipRequest(Schema):
    """Wire contract for PhoneOwnershipRequest."""

    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        if not ContactMethod.normalize_phone(value):
            raise ValueError("Phone number must contain at least one digit")
        return value


# ── Supplier search aliases ──────────────────────────────────────────────


class SupplierSearchAliasOut(Schema):
    """Wire contract for SupplierSearchAliasOut."""

    id: UUID
    company: UUID
    alias: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_company(obj: SupplierSearchAlias) -> UUID:
        """Serialize the FK as its id (ninja would read the related instance)."""
        return obj.company_id


class SupplierSearchAliasCreateRequest(Schema):
    """Wire contract for SupplierSearchAliasCreateRequest."""

    alias: str

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str) -> str:
        alias = value.strip()
        if not alias:
            raise ValueError("Alias is required")
        if len(alias) > 255:
            raise ValueError("Alias must be at most 255 characters")
        return alias


# ── Contact methods ──────────────────────────────────────────────────────


class ContactMethodOut(Schema):
    """Wire contract for ContactMethodOut."""

    id: UUID
    company: UUID | None
    owner_company: str
    company_name: str
    person: UUID | None
    person_name: str
    method_type: MethodType
    value: str
    normalized_value: str
    label: str | None
    is_primary: bool
    source: MethodSource
    created_at: datetime
    updated_at: datetime


class ContactMethodRequest(Schema):
    """Wire contract for ContactMethodRequest."""

    company: UUID | None = None
    person: UUID | None = None
    method_type: MethodType
    value: str
    label: str | None = None
    is_primary: bool = False
    source: MethodSource = "local"


class PatchedContactMethodRequest(Schema):
    """Wire contract for PatchedContactMethodRequest."""

    company: UUID | None = None
    person: UUID | None = None
    method_type: MethodType | None = None
    value: str | None = None
    label: str | None = None
    is_primary: bool | None = None
    source: MethodSource | None = None


class PaginatedContactMethodList(Schema):
    """Wire contract for PaginatedContactMethodList."""

    results: list[ContactMethodOut]
    count: int
    page: int
    page_size: int
    total_pages: int


# ── Supplier pickup addresses ────────────────────────────────────────────


class SupplierPickupAddressOut(Schema):
    """Wire contract for SupplierPickupAddressOut."""

    id: UUID
    company: UUID
    name: str
    street: str
    suburb: str | None
    city: str
    state: str | None
    postal_code: str | None
    country: str
    google_place_id: str | None
    latitude: float | None
    longitude: float | None
    is_primary: bool
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    formatted_address: str


class SupplierPickupAddressRequest(Schema):
    """Create or full-update payload for a supplier pickup address.

    Nullable text fields reject blank strings and use null for an unset value
    (ADR 0040).
    """

    company: UUID
    name: str
    street: str
    city: str
    suburb: NullableText = None
    state: NullableText = None
    postal_code: NullableText = None
    country: str = "New Zealand"
    google_place_id: NullableText = None
    latitude: float | None = None
    longitude: float | None = None
    is_primary: bool = False
    notes: NullableText = None


class PatchedSupplierPickupAddressRequest(Schema):
    """Wire contract for PatchedSupplierPickupAddressRequest."""

    company: UUID | None = None
    name: str | None = None
    street: str | None = None
    city: str | None = None
    suburb: NullableText = None
    state: NullableText = None
    postal_code: NullableText = None
    country: str | None = None
    google_place_id: NullableText = None
    latitude: float | None = None
    longitude: float | None = None
    is_primary: bool | None = None
    notes: NullableText = None


# ── People directory ─────────────────────────────────────────────────────


class PersonCompanySummary(Schema):
    """Wire contract for PersonCompanySummary."""

    company_id: UUID
    company_name: str


class PersonSummary(Schema):
    """Wire contract for PersonSummary."""

    id: UUID
    name: str
    email: str | None
    is_active: bool
    primary_phone: str
    companies: list[PersonCompanySummary]


class PaginatedPersonSummaryList(Schema):
    """Wire contract for PaginatedPersonSummaryList."""

    results: list[PersonSummary]
    count: int
    page: int
    page_size: int
    total_pages: int


class PersonDetail(Schema):
    """Full person body returned by reads and identity updates.

    Identity-update responses deliberately return the complete detail shape so
    the client can replace its cached person without a follow-up request.
    """

    id: UUID
    name: str
    email: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    primary_phone: str
    companies: list[PersonCompanySummary]
    company_links: list[PersonCompanyLink]


class PersonIdentityUpdateRequest(Schema):
    """Wire contract for PersonIdentityUpdateRequest."""

    name: str | None = None
    email: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return clean_optional_email(value)


class CompanyLinkWriteRequest(Schema):
    """Wire contract for CompanyLinkWriteRequest."""

    position: str | None = None
    notes: str | None = None
    is_primary: bool = False


class PersonContactMethodWriteRequest(Schema):
    """Wire contract for PersonContactMethodWriteRequest."""

    method_type: MethodType
    value: str
    is_primary: bool = False
    label: str | None = None


class PatchedPersonContactMethodWriteRequest(Schema):
    """Wire contract for PatchedPersonContactMethodWriteRequest."""

    method_type: MethodType | None = None
    value: str | None = None
    is_primary: bool | None = None
    label: str | None = None


# ── Address validation ───────────────────────────────────────────────────


class AddressValidateRequest(Schema):
    """Body for companies_addresses_validate_create."""

    address: str


class AddressCandidate(Schema):
    """One structured candidate from the Google Address Validation API."""

    formatted_address: str
    street: str
    suburb: str
    city: str
    state: str
    postal_code: str
    country: str
    google_place_id: str
    latitude: float | None
    longitude: float | None


class AddressValidateResponse(Schema):
    """Response for companies_addresses_validate_create."""

    candidates: list[AddressCandidate]


# ── Data quality: duplicate identities ───────────────────────────────────


class DuplicateIdentityEvidenceOut(Schema):
    """Wire contract for DuplicateIdentityEvidenceOut."""

    kind: str
    normalized_value: str
    owner_count: int


class DuplicateCompanyMemberOut(Schema):
    """Wire contract for DuplicateCompanyMemberOut."""

    company_id: UUID
    name: str
    email: str | None
    address: str | None
    allow_jobs: bool
    is_account_customer: bool
    is_supplier: bool
    xero_archived: bool
    job_count: int
    contact_names: list[str]


class DuplicatePersonCompanyLinkOut(Schema):
    """Wire contract for DuplicatePersonCompanyLinkOut."""

    link_id: UUID
    company_id: UUID
    company_name: str
    position: str | None
    is_primary: bool
    is_active: bool


class DuplicatePersonContactMethodOut(Schema):
    """Wire contract for DuplicatePersonContactMethodOut."""

    method_id: UUID
    method_type: MethodType
    value: str
    normalized_value: str
    contact_label: str | None
    is_primary: bool


class DuplicatePersonSummaryOut(Schema):
    """Wire contract for DuplicatePersonSummaryOut."""

    person_id: UUID
    name: str
    email: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    company_links: list[DuplicatePersonCompanyLinkOut]
    contact_methods: list[DuplicatePersonContactMethodOut]
    job_count: int
    phone_call_count: int


class DuplicateCompanyGroupOut(Schema):
    """Wire contract for DuplicateCompanyGroupOut."""

    group_id: str
    fingerprint: str
    recommendation: Literal["merge", "review"]
    reason_codes: list[str]
    canonical_id: UUID | None
    members: list[DuplicateCompanyMemberOut]
    evidence: list[DuplicateIdentityEvidenceOut]


class DuplicatePersonGroupOut(Schema):
    """Wire contract for DuplicatePersonGroupOut."""

    group_id: str
    fingerprint: str
    recommendation: Literal["merge", "review"]
    reason_codes: list[str]
    canonical_id: UUID | None
    members: list[DuplicatePersonSummaryOut]
    evidence: list[DuplicateIdentityEvidenceOut]


class DuplicateIdentityReportSummaryOut(Schema):
    """Wire contract for DuplicateIdentityReportSummaryOut."""

    company_merge_groups: int
    company_review_groups: int
    person_merge_groups: int
    person_review_groups: int


class DuplicateIdentitiesResponse(Schema):
    """Wire contract for DuplicateIdentitiesResponse."""

    company_groups: list[DuplicateCompanyGroupOut]
    person_groups: list[DuplicatePersonGroupOut]
    summary: DuplicateIdentityReportSummaryOut
    checked_at: datetime


# ── Data quality: duplicate phones ───────────────────────────────────────


class DuplicatePhoneOwnerOut(Schema):
    """Wire contract for DuplicatePhoneOwnerOut."""

    method_id: str
    owner_kind: str
    owner_name: str
    effective_company_id: str | None


class DuplicatePhoneIssueOut(Schema):
    """Wire contract for DuplicatePhoneIssueOut."""

    normalized_value: str
    issue: str
    endpoint_label: str | None
    owners: list[DuplicatePhoneOwnerOut]


class DuplicatePhoneSummaryOut(Schema):
    """Wire contract for DuplicatePhoneSummaryOut."""

    cross_company: int
    internal_line: int


class DuplicatePhonesResponse(Schema):
    """Wire contract for DuplicatePhonesResponse."""

    duplicate_phones: list[DuplicatePhoneIssueOut]
    summary: DuplicatePhoneSummaryOut
    checked_at: datetime
