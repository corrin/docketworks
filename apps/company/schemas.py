"""Request/response schemas for the company + people endpoints.

Shapes ported from v1's generated OpenAPI schema (frontend/schema.yml) /
``apps/company/serializers.py`` + ``person_serializers.py`` so the generated
frontend client keeps working unchanged. Error responses use the standard v2
envelope (``{"detail", "error_id"}``, ADR 0013) instead of v1's per-endpoint
error serializers — recorded in the parity ledger.

Schemas here are pure shape declarations; payload building lives in the
service formatters (one implementation per concept, ADR 0039).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email as django_validate_email
from ninja import Schema
from pydantic import field_validator

from apps.company.models import ContactMethod, SupplierSearchAlias
from apps.core.schemas import NullableText

MethodType = Literal["phone", "email"]
MethodSource = Literal["imported", "local"]


def clean_optional_email(value: str | None) -> str | None:
    """Validate an optional email (v1 DRF EmailField: null ok, blank/invalid not).

    The ONE email-validation implementation (ADR 0039); purchasing reuses it
    for the PO email endpoint's recipient override. Django's validator is what
    v1's DRF EmailField used underneath, so the accepted set is identical.
    """
    if value is None:
        return None
    try:
        django_validate_email(value)
    except DjangoValidationError as exc:
        raise ValueError("Enter a valid email address.") from exc
    return value


def _require_phone_digits(value: str | None) -> str | None:
    """Reject phone values that normalize to nothing (v1 validate_phone)."""
    if value and not ContactMethod.normalize_phone(value):
        raise ValueError("Phone number must contain at least one digit")
    return value


# ── Companies ────────────────────────────────────────────────────────────


class CompanySearchQuery(Schema):
    """Query params for companies_search_retrieve (v1 CompanySearchRestView)."""

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
    """v1 CompanyNameOnlySerializer — dropdown row."""

    id: str
    name: str


class CompanySearchResult(Schema):
    """v1 CompanySearchResultSerializer — one search/list row."""

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
    """v1 CompanySearchResponseSerializer — paginated search page."""

    results: list[CompanySearchResult]
    count: int
    page: int
    page_size: int
    total_pages: int


class CompanyDetailResponse(Schema):
    """v1 CompanyDetailResponseSerializer."""

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
    """v1 CompanyCreateSerializer."""

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
    """v1 CompanyCreateResponseSerializer."""

    success: bool
    company: CompanySearchResult
    message: str


class CompanyUpdateRequest(Schema):
    """v1 CompanyUpdateSerializer — every field optional; presence matters.

    ``phone`` upserts/clears the primary ContactMethod: supplied-and-blank
    clears it, omitted leaves methods untouched (use ``model_dump(
    exclude_unset=True)``).
    """

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    is_account_customer: bool | None = None
    allow_jobs: bool | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return clean_optional_email(value)


class CompanyUpdateResponse(Schema):
    """v1 CompanyUpdateResponseSerializer."""

    success: bool
    company: CompanyDetailResponse
    message: str


class CompanyJobCompanyRef(Schema):
    """Company reference embedded in a job header row."""

    id: str
    name: str


class CompanyJobHeader(Schema):
    """v1 CompanyJobHeaderSerializer."""

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
    """v1 CompanyJobsResponseSerializer."""

    results: list[CompanyJobHeader]


# ── Company people (links) ───────────────────────────────────────────────


class CompanyPerson(Schema):
    """v1 CompanyPersonSerializer — a person row under a company."""

    person_id: UUID
    person_name: str
    person_email: str | None
    primary_phone: str
    position: str | None
    is_primary: bool
    notes: str | None


class CompanyPersonCreateRequest(Schema):
    """v1 CompanyPersonCreateSerializer."""

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
    """v1 PersonCompanyLinkSerializer — one company relationship."""

    company_id: UUID
    company_name: str
    position: str | None
    is_primary: bool
    notes: str | None
    is_active: bool


class PhonePersonMatch(Schema):
    """v1 PhonePersonMatchSerializer."""

    person_id: UUID
    person_name: str
    person_email: str | None
    company_links: list[PersonCompanyLink]


class PhoneCompanyOwner(Schema):
    """v1 PhoneCompanyOwnerSerializer."""

    company_id: UUID
    company_name: str


class PhoneOwnership(Schema):
    """v1 PhoneOwnershipSerializer (and its 409-conflict twin)."""

    status: Literal["available", "people", "company", "internal"]
    normalized_phone: str
    can_create_person: bool
    people: list[PhonePersonMatch]
    companies: list[PhoneCompanyOwner]


class PhoneOwnershipRequest(Schema):
    """v1 PhoneOwnershipRequestSerializer."""

    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        if not ContactMethod.normalize_phone(value):
            raise ValueError("Phone number must contain at least one digit")
        return value


# ── Supplier search aliases ──────────────────────────────────────────────


class SupplierSearchAliasOut(Schema):
    """v1 SupplierSearchAliasSerializer."""

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
    """v1 SupplierSearchAliasCreateSerializer."""

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
    """v1 ContactMethodSerializer response shape."""

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
    """v1 ContactMethodRequest — create/full-update payload."""

    company: UUID | None = None
    person: UUID | None = None
    method_type: MethodType
    value: str
    label: str | None = None
    is_primary: bool = False
    source: MethodSource = "local"


class PatchedContactMethodRequest(Schema):
    """v1 PatchedContactMethodRequest — partial-update payload."""

    company: UUID | None = None
    person: UUID | None = None
    method_type: MethodType | None = None
    value: str | None = None
    label: str | None = None
    is_primary: bool | None = None
    source: MethodSource | None = None


class PaginatedContactMethodList(Schema):
    """v1 PageSizePagination envelope over ContactMethod rows."""

    results: list[ContactMethodOut]
    count: int
    page: int
    page_size: int
    total_pages: int


# ── Supplier pickup addresses ────────────────────────────────────────────


class SupplierPickupAddressOut(Schema):
    """v1 SupplierPickupAddressSerializer response shape."""

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
    """v1 SupplierPickupAddressRequest — create/full-update payload.

    Empty strings on nullable fields are coerced to None (v1
    ``to_internal_value`` behaviour).
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
    """v1 PatchedSupplierPickupAddressRequest — partial-update payload."""

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
    """v1 PersonCompanySummarySerializer."""

    company_id: UUID
    company_name: str


class PersonSummary(Schema):
    """v1 PersonSummarySerializer — directory row."""

    id: UUID
    name: str
    email: str | None
    is_active: bool
    primary_phone: str
    companies: list[PersonCompanySummary]


class PaginatedPersonSummaryList(Schema):
    """v1 PageSizePagination envelope over PersonSummary rows."""

    results: list[PersonSummary]
    count: int
    page: int
    page_size: int
    total_pages: int


class PersonDetail(Schema):
    """v1 PersonDetailSerializer.

    Also the PUT/PATCH response: v1's implementation returned the full
    detail body from identity updates (its schema.yml said
    PersonIdentityUpdate; the wire carried PersonDetail — v2 declares what
    the wire carried).
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
    """v1 PersonIdentityUpdateSerializer — optional identity fields."""

    name: str | None = None
    email: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return clean_optional_email(value)


class CompanyLinkWriteRequest(Schema):
    """v1 CompanyLinkWriteSerializer."""

    position: str | None = None
    notes: str | None = None
    is_primary: bool = False


class PersonContactMethodWriteRequest(Schema):
    """v1 PersonContactMethodWriteSerializer."""

    method_type: MethodType
    value: str
    is_primary: bool = False
    label: str | None = None


class PatchedPersonContactMethodWriteRequest(Schema):
    """v1 PatchedPersonContactMethodWriteRequest — partial update."""

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
    """v1 DuplicateIdentityEvidence — one corroborating signal."""

    kind: str
    normalized_value: str
    owner_count: int


class DuplicateCompanyMemberOut(Schema):
    """v1 DuplicateCompanyMember row."""

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
    """v1 DuplicatePersonCompanyLink row."""

    link_id: UUID
    company_id: UUID
    company_name: str
    position: str | None
    is_primary: bool
    is_active: bool


class DuplicatePersonContactMethodOut(Schema):
    """v1 DuplicatePersonContactMethod row."""

    method_id: UUID
    method_type: MethodType
    value: str
    normalized_value: str
    contact_label: str | None
    is_primary: bool


class DuplicatePersonSummaryOut(Schema):
    """v1 DuplicatePersonSummary — one person member with merge context."""

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
    """v1 DuplicateCompanyGroup."""

    group_id: str
    fingerprint: str
    recommendation: Literal["merge", "review"]
    reason_codes: list[str]
    canonical_id: UUID | None
    members: list[DuplicateCompanyMemberOut]
    evidence: list[DuplicateIdentityEvidenceOut]


class DuplicatePersonGroupOut(Schema):
    """v1 DuplicatePersonGroup."""

    group_id: str
    fingerprint: str
    recommendation: Literal["merge", "review"]
    reason_codes: list[str]
    canonical_id: UUID | None
    members: list[DuplicatePersonSummaryOut]
    evidence: list[DuplicateIdentityEvidenceOut]


class DuplicateIdentityReportSummaryOut(Schema):
    """v1 DuplicateIdentityReportSummary counts."""

    company_merge_groups: int
    company_review_groups: int
    person_merge_groups: int
    person_review_groups: int


class DuplicateIdentitiesResponse(Schema):
    """v1 DuplicateIdentitiesResponseSerializer."""

    company_groups: list[DuplicateCompanyGroupOut]
    person_groups: list[DuplicatePersonGroupOut]
    summary: DuplicateIdentityReportSummaryOut
    checked_at: datetime


# ── Data quality: duplicate phones ───────────────────────────────────────


class DuplicatePhoneOwnerOut(Schema):
    """v1 DuplicatePhoneOwner — one owner of a mis-owned number."""

    method_id: str
    owner_kind: str
    owner_name: str
    effective_company_id: str | None


class DuplicatePhoneIssueOut(Schema):
    """v1 DuplicatePhoneIssue — one problematic number and its owners."""

    normalized_value: str
    issue: str
    endpoint_label: str | None
    owners: list[DuplicatePhoneOwnerOut]


class DuplicatePhoneSummaryOut(Schema):
    """v1 DuplicatePhoneSummary counts."""

    cross_company: int
    internal_line: int


class DuplicatePhonesResponse(Schema):
    """v1 DuplicatePhonesResponseSerializer."""

    duplicate_phones: list[DuplicatePhoneIssueOut]
    summary: DuplicatePhoneSummaryOut
    checked_at: datetime
