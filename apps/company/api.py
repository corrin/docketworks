"""The company domain's ninja router (thin translators over the services).

``/api/companies/`` exposes company CRUD, people links, phone ownership,
supplier aliases, contact methods, and pickup addresses. ``/api/people/``
provides the person directory. Company-domain data-quality reports retain their
``/api/job/data-quality/`` URLs but live here so the concept has one home
(ADR 0039).

Error bodies use the standard envelope from ADR 0013. People and data-quality
endpoints require office staff.

Integration wiring (config/api.py): ``api.add_router("/", router)`` — the
paths below carry their own full prefixes.
"""

import logging
from dataclasses import asdict, dataclass
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import InvalidPage, Paginator
from django.db import IntegrityError, transaction
from django.db.models import Model, QuerySet
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.company.models import (
    Company,
    CompanyPersonLink,
    ContactMethod,
    Person,
    SupplierPickupAddress,
    SupplierSearchAlias,
)
from apps.company.schemas import (
    AddressValidateRequest,
    AddressValidateResponse,
    CompanyCreateRequest,
    CompanyCreateResponse,
    CompanyDetailResponse,
    CompanyJobsResponse,
    CompanyLinkWriteRequest,
    CompanyNameOnly,
    CompanyPerson,
    CompanyPersonCreateRequest,
    CompanySearchQuery,
    CompanySearchResponse,
    CompanyUpdateRequest,
    CompanyUpdateResponse,
    ContactMethodListQuery,
    ContactMethodOut,
    ContactMethodRequest,
    DuplicateIdentitiesResponse,
    DuplicatePhonesResponse,
    PaginatedContactMethodList,
    PaginatedPersonSummaryList,
    PatchedContactMethodRequest,
    PatchedPersonContactMethodWriteRequest,
    PatchedSupplierPickupAddressRequest,
    PersonCompanyLink,
    PersonContactMethodWriteRequest,
    PersonDetail,
    PersonIdentityUpdateRequest,
    PhoneOwnership,
    PhoneOwnershipRequest,
    SupplierPickupAddressOut,
    SupplierPickupAddressRequest,
    SupplierSearchAliasCreateRequest,
    SupplierSearchAliasOut,
)
from apps.company.services.company_rest_service import (
    CompanyCreateData,
    CompanyDetailData,
    CompanyNameData,
    CompanyRestService,
    CompanySearchPage,
    CompanyUpdateData,
    PickupAddressData,
    ProviderAuthRequiredError,
    annotated_with_phone,
    pickup_address_data,
)
from apps.company.services.contact_methods import (
    ContactMethodData,
    ContactMethodWriteData,
    contact_method_data,
    contact_method_queryset,
    delete_contact_method,
    save_contact_method,
)
from apps.company.services.duplicate_identity_report import (
    DuplicateIdentityReport,
    DuplicateIdentityReportService,
)
from apps.company.services.duplicate_phone_report import (
    DuplicatePhoneReportService,
    DuplicatePhonesReport,
)
from apps.company.services.geocoding_service import (
    GeocodingError,
    GeocodingNotConfiguredError,
    geocode_address,
)
from apps.company.services.person_service import (
    CompanyLinkData,
    CompanyPersonData,
    NewPersonData,
    PersonCompanyLinkData,
    PersonDetailData,
    PersonDirectoryService,
    PersonPhoneConflictError,
    PhoneOwnershipResult,
    archive_person,
    classify_phone_ownership,
    company_person_data,
    create_person_for_company,
    put_company_link,
    remove_company_link,
)
from apps.core.auth import CookieJWTAuth, OfficeStaffCookieJWTAuth
from apps.core.errors import persist_app_error

logger = logging.getLogger(__name__)

router = Router()


# ── Auth ─────────────────────────────────────────────────────────────────
#
# OfficeStaffCookieJWTAuth started life here; it moved to apps/core/auth.py
# when the job app became its second consumer (ADR 0039).

auth = CookieJWTAuth()
office_auth = OfficeStaffCookieJWTAuth()


# ── Pagination (v1 PageSizePagination wire contract) ─────────────────────

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class PageData[M: Model]:
    """One page of rows plus the v1 pagination envelope numbers."""

    rows: list[M]
    count: int
    page: int
    page_size: int
    total_pages: int


def paginate[M: Model](queryset: QuerySet[M], *, page: int, page_size: int | None) -> PageData[M]:
    """Slice ``queryset`` DRF-style; raise Http404 for an out-of-range page.

    Envelope: ``{"results", "count", "page", "page_size", "total_pages"}``
    with a default page size of 50 and a ``page_size`` query param capped at
    100 (v1 ``PageSizePagination``). Lives here because the company app is
    currently its only consumer; hoist to ``apps/core`` when a second domain
    app pages a list.
    """
    if page_size is None or page_size <= 0:
        effective_size = DEFAULT_PAGE_SIZE
    else:
        effective_size = min(page_size, MAX_PAGE_SIZE)
    paginator = Paginator(queryset, effective_size)
    try:
        page_obj = paginator.page(page)
    except InvalidPage as exc:
        raise Http404(f"Invalid page ({page}): {exc}") from exc
    return PageData(
        rows=list(page_obj.object_list),
        count=paginator.count,
        page=page_obj.number,
        page_size=effective_size,
        total_pages=paginator.num_pages,
    )


def validation_message(exc: Exception) -> str:
    """Flatten a Django ValidationError (or ValueError) into one message."""
    if isinstance(exc, DjangoValidationError):
        return "; ".join(exc.messages)
    return str(exc)


# ── Companies: CRUD / search / jobs ──────────────────────────────────────


@router.get(
    "/companies/all/",
    auth=auth,
    operation_id="companies_all_list",
    response=list[CompanyNameOnly],
    summary="List all companies",
    tags=["Companies"],
)
def companies_all_list(request: HttpRequest) -> list[CompanyNameData]:
    """All companies (id + name only) for dropdowns and advanced search."""
    return CompanyRestService.get_all_companies()


@router.get(
    "/companies/search/",
    auth=auth,
    operation_id="companies_search_retrieve",
    response=CompanySearchResponse,
    summary="Search companies",
    tags=["Companies"],
)
def companies_search_retrieve(
    request: HttpRequest,
    params: Query[CompanySearchQuery],
) -> CompanySearchPage:
    """List/search companies with pagination and sorting."""
    query = params.q.strip()
    page = max(1, params.page)
    # Clamp to the same MAX_PAGE_SIZE contract the paginate() helper enforces
    # (v1 PageSizePagination capped at 100; ranked search bypassed the helper).
    page_size = min(max(1, params.page_size), MAX_PAGE_SIZE)
    result = CompanyRestService.list_companies(
        query=query if len(query) >= 3 else None,
        page=page,
        page_size=page_size,
        sort_by=params.sort_by,
        sort_dir=params.sort_dir,
    )
    CompanyRestService.log_company_search_results(
        request=request,
        source="company_search",
        query=query,
        companies=result["results"],
        total_count=result["count"],
    )
    return result


@router.post(
    "/companies/create/",
    auth=auth,
    operation_id="companies_create_create",
    response={201: CompanyCreateResponse},
    summary="Create a new company",
    tags=["Companies"],
)
def companies_create_create(
    request: HttpRequest, payload: CompanyCreateRequest
) -> Status[dict[str, object]]:
    """Create a company: provider duplicate check first, local write, then push.

    Business failures keep v1's status mapping: duplicate contact -> 409,
    provider unauthenticated -> 401, other validation -> 400. Only genuinely
    unexpected failures reach the 500 envelope.
    """
    data: CompanyCreateData = {
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "address": payload.address,
        "is_account_customer": payload.is_account_customer,
        "allow_jobs": payload.allow_jobs,
    }
    try:
        created = CompanyRestService.create_company(data)
    except ProviderAuthRequiredError as exc:
        raise HttpError(401, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    annotated = (
        Company.objects.with_invoice_summary()
        .annotate(phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk"))
        .get(id=created.id)
    )
    return Status(
        201,
        {
            "success": True,
            "company": CompanyRestService._format_company_summary(annotated_with_phone(annotated)),
            "message": f'Company "{annotated.name}" created successfully',
        },
    )


@router.get(
    "/companies/{uuid:company_id}/",
    auth=auth,
    operation_id="companies_retrieve",
    response=CompanyDetailResponse,
    summary="Get company details",
    tags=["Companies"],
)
def companies_retrieve(request: HttpRequest, company_id: UUID) -> CompanyDetailData:
    """Retrieve detailed information for a specific company."""
    try:
        return CompanyRestService.get_company_by_id(company_id)
    except ValueError as exc:
        raise Http404(str(exc)) from exc


def _update_company(company_id: UUID, payload: CompanyUpdateRequest) -> dict[str, object]:
    supplied = payload.model_dump(exclude_unset=True)
    data: CompanyUpdateData = {}
    # No `is not None` guards: the schema now rejects null on the non-nullable
    # fields, so a null that used to be dropped here (200, nothing changed) is
    # a 422 before the handler runs. Presence is the only question left.
    if "name" in supplied:
        data["name"] = payload.name
    if "email" in supplied:
        data["email"] = payload.email
    if "phone" in supplied:
        data["phone"] = payload.phone
    if "address" in supplied:
        data["address"] = payload.address
    if "is_account_customer" in supplied:
        data["is_account_customer"] = payload.is_account_customer
    if "allow_jobs" in supplied:
        data["allow_jobs"] = payload.allow_jobs

    try:
        updated = CompanyRestService.update_company(company_id, data)
    except ProviderAuthRequiredError as exc:
        raise HttpError(401, str(exc)) from exc
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise Http404(str(exc)) from exc
        raise HttpError(400, str(exc)) from exc

    return {
        "success": True,
        "company": CompanyRestService._format_company_detail(updated),
        "message": f'Company "{updated.name}" updated successfully',
    }


@router.put(
    "/companies/{uuid:company_id}/update/",
    auth=auth,
    operation_id="companies_update_update",
    response=CompanyUpdateResponse,
    summary="Update company",
    tags=["Companies"],
)
def companies_update_update(
    request: HttpRequest, company_id: UUID, payload: CompanyUpdateRequest
) -> dict[str, object]:
    """Full update of company information."""
    return _update_company(company_id, payload)


@router.patch(
    "/companies/{uuid:company_id}/update/",
    auth=auth,
    operation_id="companies_update_partial_update",
    response=CompanyUpdateResponse,
    summary="Partially update company",
    tags=["Companies"],
)
def companies_update_partial_update(
    request: HttpRequest, company_id: UUID, payload: CompanyUpdateRequest
) -> dict[str, object]:
    """Partial update of company information."""
    return _update_company(company_id, payload)


@router.get(
    "/companies/{uuid:company_id}/jobs/",
    auth=auth,
    operation_id="companies_jobs_retrieve",
    response=CompanyJobsResponse,
    summary="Get company jobs",
    tags=["Companies"],
)
def companies_jobs_retrieve(request: HttpRequest, company_id: UUID) -> dict[str, object]:
    """Retrieve all jobs for a specific company (header rows, newest first)."""
    try:
        return {"results": CompanyRestService.get_company_jobs(company_id)}
    except ValueError as exc:
        raise Http404(str(exc)) from exc


# ── Company people (v1 CompanyPeopleView / phone ownership) ──────────────


@router.get(
    "/companies/{uuid:company_id}/people/",
    auth=office_auth,
    operation_id="companies_people_list",
    response=list[CompanyPerson],
    tags=["companies"],
)
def companies_people_list(request: HttpRequest, company_id: UUID) -> list[CompanyPersonData]:
    """List a company's active people with their primary phones."""
    company = get_object_or_404(Company, id=company_id)
    links = (
        CompanyPersonLink.objects.filter(company=company, is_active=True)
        .select_related("person")
        .annotate(phone=ContactMethod.primary_phone_for_link_annotation())
        .order_by("-is_primary", "person__name")
    )
    return [company_person_data(link) for link in links]


@router.post(
    "/companies/{uuid:company_id}/people/",
    auth=office_auth,
    operation_id="companies_people_create",
    response={201: CompanyPerson, 409: PhoneOwnership},
    tags=["companies"],
)
def companies_people_create(
    request: HttpRequest, company_id: UUID, payload: CompanyPersonCreateRequest
) -> Status[CompanyPersonData | PhoneOwnershipResult]:
    """Create a Person with its initial company link, enforcing phone ownership."""
    company = get_object_or_404(Company, id=company_id)
    data: NewPersonData = {
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "position": payload.position,
        "notes": payload.notes,
        "is_primary": payload.is_primary,
    }
    try:
        link = create_person_for_company(company=company, data=data)
    # deliberate-swallow: reshaped into the 409 response with the conflict payload
    except PersonPhoneConflictError as exc:
        return Status(409, exc.ownership)
    annotated = (
        CompanyPersonLink.objects.select_related("person")
        .annotate(phone=ContactMethod.primary_phone_for_link_annotation())
        .get(pk=link.pk)
    )
    return Status(201, company_person_data(annotated))


@router.post(
    "/companies/{uuid:company_id}/people/phone-ownership/",
    auth=office_auth,
    operation_id="companies_people_phone_ownership_create",
    response=PhoneOwnership,
    tags=["companies"],
)
def companies_people_phone_ownership_create(
    request: HttpRequest, company_id: UUID, payload: PhoneOwnershipRequest
) -> PhoneOwnershipResult:
    """Classify a phone number before creating a Person for a company."""
    company = get_object_or_404(Company, id=company_id)
    return classify_phone_ownership(company=company, raw_phone=payload.phone)


# ── Supplier search aliases (v1 supplier_search_alias_views.py) ──────────


@router.get(
    "/companies/{uuid:company_id}/supplier-aliases/",
    auth=auth,
    operation_id="companies_supplier_aliases_list",
    response=list[SupplierSearchAliasOut],
    summary="List supplier search aliases",
    tags=["Companies"],
)
def companies_supplier_aliases_list(
    request: HttpRequest, company_id: UUID
) -> list[SupplierSearchAlias]:
    """List a company's active supplier search aliases."""
    company = get_object_or_404(Company, id=company_id)
    return list(company.supplier_search_aliases.filter(is_active=True).order_by("alias"))


@router.post(
    "/companies/{uuid:company_id}/supplier-aliases/",
    auth=auth,
    operation_id="companies_supplier_aliases_create",
    response={201: SupplierSearchAliasOut},
    summary="Create supplier search alias",
    tags=["Companies"],
)
def companies_supplier_aliases_create(
    request: HttpRequest, company_id: UUID, payload: SupplierSearchAliasCreateRequest
) -> Status[SupplierSearchAlias]:
    """Create (or reactivate) a supplier search alias for a company."""
    company = get_object_or_404(Company, id=company_id)
    alias, _created = SupplierSearchAlias.objects.get_or_create(
        company=company,
        alias=payload.alias,
        defaults={"is_active": True},
    )
    if not alias.is_active:
        alias.is_active = True
        alias.save(update_fields=["is_active", "updated_at"])
    return Status(201, alias)


@router.delete(
    "/companies/supplier-aliases/{uuid:alias_id}/",
    auth=auth,
    operation_id="companies_supplier_aliases_destroy",
    response={204: None},
    summary="Deactivate supplier search alias",
    tags=["Companies"],
)
def companies_supplier_aliases_destroy(request: HttpRequest, alias_id: UUID) -> Status[None]:
    """Deactivate a supplier search alias (soft delete)."""
    alias = get_object_or_404(SupplierSearchAlias, id=alias_id, is_active=True)
    alias.is_active = False
    alias.save(update_fields=["is_active", "updated_at"])
    return Status(204, None)


# ── Address validation (v1 address_views.AddressValidateView) ────────────


@router.post(
    "/companies/addresses/validate/",
    auth=auth,
    operation_id="companies_addresses_validate_create",
    response=AddressValidateResponse,
    tags=["companies"],
)
def companies_addresses_validate_create(
    request: HttpRequest, payload: AddressValidateRequest
) -> dict[str, list[dict[str, object]]]:
    """Validate a freetext address and return structured candidates.

    503 when the Google API is unavailable or the Google Maps API key is not
    configured (v1 behaviour).
    """
    address = payload.address.strip()
    if not address:
        raise HttpError(400, "Address is required")

    try:
        result = geocode_address(address)
    except GeocodingNotConfiguredError as exc:
        logger.warning("Google Maps API key not set on IntegrationSettings")
        raise HttpError(503, "Address validation service not configured") from exc
    except GeocodingError as exc:
        persist_app_error(exc)
        logger.exception("Address validation failed")
        raise HttpError(503, str(exc)) from exc
    if result is not None:
        return {"candidates": [asdict(result)]}
    return {"candidates": []}


# ── Contact methods (v1 ContactMethodViewSet) ────────────────────────────


@router.get(
    "/companies/contact-methods/",
    auth=auth,
    operation_id="companies_contact_methods_list",
    response=PaginatedContactMethodList,
    tags=["companies"],
)
def companies_contact_methods_list(
    request: HttpRequest,
    params: Query[ContactMethodListQuery],
) -> dict[str, object]:
    """List contact methods, filterable by owning company/person and type."""
    queryset = contact_method_queryset()
    if params.company_id:
        queryset = queryset.filter(company_id=params.company_id) | queryset.filter(
            person__company_links__company_id=params.company_id,
            person__company_links__is_active=True,
        )
    if params.person_id:
        queryset = queryset.filter(person_id=params.person_id)
    if params.method_type:
        queryset = queryset.filter(method_type=params.method_type)
    queryset = queryset.distinct().order_by("method_type", "-is_primary", "value")
    page_data = paginate(queryset, page=params.page, page_size=params.page_size)
    return {
        "results": [contact_method_data(method) for method in page_data.rows],
        "count": page_data.count,
        "page": page_data.page,
        "page_size": page_data.page_size,
        "total_pages": page_data.total_pages,
    }


@router.post(
    "/companies/contact-methods/",
    auth=auth,
    operation_id="companies_contact_methods_create",
    response={201: ContactMethodOut},
    tags=["companies"],
)
def companies_contact_methods_create(
    request: HttpRequest, payload: ContactMethodRequest
) -> Status[ContactMethodData]:
    """Create a contact method for a company or person."""
    data: ContactMethodWriteData = {
        "company": payload.company,
        "person": payload.person,
        "method_type": payload.method_type,
        "value": payload.value,
        "label": payload.label,
        "is_primary": payload.is_primary,
        "source": payload.source,
    }
    try:
        method = save_contact_method(data)
    except (DjangoValidationError, ValueError) as exc:
        raise HttpError(400, validation_message(exc)) from exc
    return Status(201, contact_method_data(method))


@router.get(
    "/companies/contact-methods/{uuid:id}/",
    auth=auth,
    operation_id="companies_contact_methods_retrieve",
    response=ContactMethodOut,
    tags=["companies"],
)
def companies_contact_methods_retrieve(request: HttpRequest, id: UUID) -> ContactMethodData:
    """Retrieve one contact method."""
    method = get_object_or_404(contact_method_queryset(), id=id)
    return contact_method_data(method)


def _contact_method_write_data(
    payload: ContactMethodRequest | PatchedContactMethodRequest,
) -> ContactMethodWriteData:
    supplied = payload.model_dump(exclude_unset=True)
    data: ContactMethodWriteData = {}
    if "company" in supplied:
        data["company"] = payload.company
    if "person" in supplied:
        data["person"] = payload.person
    if "method_type" in supplied:
        data["method_type"] = payload.method_type
    if "value" in supplied:
        data["value"] = payload.value
    if "label" in supplied:
        data["label"] = payload.label
    if "is_primary" in supplied:
        data["is_primary"] = payload.is_primary
    if "source" in supplied:
        data["source"] = payload.source
    return data


@router.put(
    "/companies/contact-methods/{uuid:id}/",
    auth=auth,
    operation_id="companies_contact_methods_update",
    response=ContactMethodOut,
    tags=["companies"],
)
def companies_contact_methods_update(
    request: HttpRequest, id: UUID, payload: ContactMethodRequest
) -> ContactMethodData:
    """Full update of one contact method."""
    method = get_object_or_404(ContactMethod, id=id)
    try:
        updated = save_contact_method(_contact_method_write_data(payload), instance=method)
    except (DjangoValidationError, ValueError) as exc:
        raise HttpError(400, validation_message(exc)) from exc
    return contact_method_data(updated)


@router.patch(
    "/companies/contact-methods/{uuid:id}/",
    auth=auth,
    operation_id="companies_contact_methods_partial_update",
    response=ContactMethodOut,
    tags=["companies"],
)
def companies_contact_methods_partial_update(
    request: HttpRequest, id: UUID, payload: PatchedContactMethodRequest
) -> ContactMethodData:
    """Partial update of one contact method."""
    method = get_object_or_404(ContactMethod, id=id)
    try:
        updated = save_contact_method(_contact_method_write_data(payload), instance=method)
    except (DjangoValidationError, ValueError) as exc:
        raise HttpError(400, validation_message(exc)) from exc
    return contact_method_data(updated)


@router.delete(
    "/companies/contact-methods/{uuid:id}/",
    auth=auth,
    operation_id="companies_contact_methods_destroy",
    response={204: None},
    tags=["companies"],
)
def companies_contact_methods_destroy(request: HttpRequest, id: UUID) -> Status[None]:
    """Delete one contact method."""
    method = get_object_or_404(ContactMethod, id=id)
    delete_contact_method(method)
    return Status(204, None)


# ── Supplier pickup addresses (v1 SupplierPickupAddressViewSet) ──────────


def _apply_pickup_address_write(
    address: SupplierPickupAddress,
    payload: SupplierPickupAddressRequest | PatchedSupplierPickupAddressRequest,
) -> SupplierPickupAddress:
    supplied = payload.model_dump(exclude_unset=True)
    if "company" in supplied and payload.company is not None:
        company = Company.objects.filter(id=payload.company).first()
        if company is None:
            raise HttpError(400, f"Company {payload.company} does not exist")
        address.company = company
    for field in (
        "name",
        "street",
        "suburb",
        "city",
        "state",
        "postal_code",
        "country",
        "google_place_id",
        "latitude",
        "longitude",
        "is_primary",
        "notes",
    ):
        if field in supplied:
            setattr(address, field, supplied[field])
    try:
        with transaction.atomic():  # savepoint: keep the connection usable on conflict
            address.save()
    except IntegrityError as exc:
        # v1's DRF unique-together validator surfaced this as a 400.
        raise HttpError(400, str(exc)) from exc
    return address


@router.get(
    "/companies/pickup-addresses/",
    auth=auth,
    operation_id="companies_pickup_addresses_list",
    response=list[SupplierPickupAddressOut],
    tags=["companies"],
)
def companies_pickup_addresses_list(
    request: HttpRequest, supplier_id: UUID | None = None
) -> list[PickupAddressData]:
    """List active pickup addresses, optionally filtered by supplier UUID."""
    queryset = SupplierPickupAddress.objects.filter(is_active=True)
    if supplier_id:
        queryset = queryset.filter(company_id=supplier_id)
    return [pickup_address_data(address) for address in queryset.order_by("-is_primary", "name")]


@router.post(
    "/companies/pickup-addresses/",
    auth=auth,
    operation_id="companies_pickup_addresses_create",
    response={201: SupplierPickupAddressOut},
    tags=["companies"],
)
def companies_pickup_addresses_create(
    request: HttpRequest, payload: SupplierPickupAddressRequest
) -> Status[PickupAddressData]:
    """Create a pickup address (any company, not just suppliers)."""
    address = _apply_pickup_address_write(SupplierPickupAddress(), payload)
    return Status(201, pickup_address_data(address))


@router.get(
    "/companies/pickup-addresses/{uuid:id}/",
    auth=auth,
    operation_id="companies_pickup_addresses_retrieve",
    response=SupplierPickupAddressOut,
    tags=["companies"],
)
def companies_pickup_addresses_retrieve(request: HttpRequest, id: UUID) -> PickupAddressData:
    """Retrieve one active pickup address."""
    address = get_object_or_404(SupplierPickupAddress, id=id, is_active=True)
    return pickup_address_data(address)


@router.put(
    "/companies/pickup-addresses/{uuid:id}/",
    auth=auth,
    operation_id="companies_pickup_addresses_update",
    response=SupplierPickupAddressOut,
    tags=["companies"],
)
def companies_pickup_addresses_update(
    request: HttpRequest, id: UUID, payload: SupplierPickupAddressRequest
) -> PickupAddressData:
    """Full update of one pickup address."""
    address = get_object_or_404(SupplierPickupAddress, id=id, is_active=True)
    return pickup_address_data(_apply_pickup_address_write(address, payload))


@router.patch(
    "/companies/pickup-addresses/{uuid:id}/",
    auth=auth,
    operation_id="companies_pickup_addresses_partial_update",
    response=SupplierPickupAddressOut,
    tags=["companies"],
)
def companies_pickup_addresses_partial_update(
    request: HttpRequest, id: UUID, payload: PatchedSupplierPickupAddressRequest
) -> PickupAddressData:
    """Partial update of one pickup address."""
    address = get_object_or_404(SupplierPickupAddress, id=id, is_active=True)
    return pickup_address_data(_apply_pickup_address_write(address, payload))


@router.delete(
    "/companies/pickup-addresses/{uuid:id}/",
    auth=auth,
    operation_id="companies_pickup_addresses_destroy",
    response={204: None},
    tags=["companies"],
)
def companies_pickup_addresses_destroy(request: HttpRequest, id: UUID) -> Status[None]:
    """Soft-delete one pickup address (sets is_active=False)."""
    address = get_object_or_404(SupplierPickupAddress, id=id, is_active=True)
    address.is_active = False
    address.save(update_fields=["is_active"])
    return Status(204, None)


# ── People directory (v1 person_views.py) ────────────────────────────────


@router.get(
    "/people/",
    auth=office_auth,
    operation_id="people_list",
    response=PaginatedPersonSummaryList,
    tags=["people"],
)
def people_list(
    request: HttpRequest,
    q: str = "",
    include_archived: bool = False,
    page: int = 1,
    page_size: int | None = None,
) -> dict[str, object]:
    """List and search active people across company relationships."""
    queryset = PersonDirectoryService.search(q, include_archived=include_archived)
    page_data = paginate(queryset, page=page, page_size=page_size)
    return {
        "results": [PersonDirectoryService.summary_data(person) for person in page_data.rows],
        "count": page_data.count,
        "page": page_data.page,
        "page_size": page_data.page_size,
        "total_pages": page_data.total_pages,
    }


@router.get(
    "/people/{uuid:person_id}/",
    auth=office_auth,
    operation_id="people_retrieve",
    response=PersonDetail,
    tags=["people"],
)
def people_retrieve(request: HttpRequest, person_id: UUID) -> PersonDetailData:
    """Retrieve a Person's identity fields and relationships."""
    person = get_object_or_404(Person, id=person_id)
    return PersonDirectoryService.detail_data(person)


def _apply_identity_update(
    person_id: UUID, payload: PersonIdentityUpdateRequest
) -> PersonDetailData:
    person = get_object_or_404(Person, id=person_id)
    supplied = payload.model_dump(exclude_unset=True)
    update_fields = ["updated_at"]
    if "name" in supplied:
        person.name = payload.name
        update_fields.append("name")
    if "email" in supplied:
        person.email = payload.email
        update_fields.append("email")
    person.save(update_fields=update_fields)
    return PersonDirectoryService.detail_data(person)


@router.put(
    "/people/{uuid:person_id}/",
    auth=office_auth,
    operation_id="people_update",
    response=PersonDetail,
    tags=["people"],
)
def people_update(
    request: HttpRequest, person_id: UUID, payload: PersonIdentityUpdateRequest
) -> PersonDetailData:
    """Update a Person's identity fields (name/email)."""
    return _apply_identity_update(person_id, payload)


@router.patch(
    "/people/{uuid:person_id}/",
    auth=office_auth,
    operation_id="people_partial_update",
    response=PersonDetail,
    tags=["people"],
)
def people_partial_update(
    request: HttpRequest, person_id: UUID, payload: PersonIdentityUpdateRequest
) -> PersonDetailData:
    """Apply a partial update to a Person's identity fields."""
    return _apply_identity_update(person_id, payload)


@router.post(
    "/people/{uuid:person_id}/archive/",
    auth=office_auth,
    operation_id="people_archive_create",
    response=PersonDetail,
    tags=["people"],
)
def people_archive_create(request: HttpRequest, person_id: UUID) -> PersonDetailData:
    """Explicitly retire a person (deactivate all links + archive)."""
    person = get_object_or_404(Person, id=person_id)
    archive_person(person=person)
    person.refresh_from_db()
    return PersonDirectoryService.detail_data(person)


@router.get(
    "/people/{uuid:person_id}/company-links/",
    auth=office_auth,
    operation_id="people_company_links_list",
    response=list[PersonCompanyLink],
    tags=["people"],
)
def people_company_links_list(request: HttpRequest, person_id: UUID) -> list[PersonCompanyLinkData]:
    """List all company relationships for a Person (active first)."""
    person = get_object_or_404(Person, id=person_id)
    return PersonDirectoryService.company_links(person)


@router.put(
    "/people/{uuid:person_id}/company-links/{uuid:company_id}/",
    auth=office_auth,
    operation_id="people_company_links_update",
    response=PersonCompanyLink,
    tags=["people"],
)
def people_company_links_update(
    request: HttpRequest,
    person_id: UUID,
    company_id: UUID,
    payload: CompanyLinkWriteRequest,
) -> PersonCompanyLinkData:
    """Create, update, or reactivate a Person-company relationship."""
    person = get_object_or_404(Person, id=person_id)
    company = get_object_or_404(Company, id=company_id)
    data: CompanyLinkData = {
        "position": payload.position,
        "notes": payload.notes,
        "is_primary": payload.is_primary,
    }
    link = put_company_link(person=person, company=company, data=data)
    return {
        "company_id": link.company_id,
        "company_name": company.name,
        "position": link.position,
        "is_primary": link.is_primary,
        "notes": link.notes,
        "is_active": link.is_active,
    }


@router.delete(
    "/people/{uuid:person_id}/company-links/{uuid:company_id}/",
    auth=office_auth,
    operation_id="people_company_links_destroy",
    response={204: None},
    tags=["people"],
)
def people_company_links_destroy(
    request: HttpRequest, person_id: UUID, company_id: UUID
) -> Status[None]:
    """Deactivate a Person-company relationship (phone-ownership guarded)."""
    person = get_object_or_404(Person, id=person_id)
    company = get_object_or_404(Company, id=company_id)
    try:
        remove_company_link(person=person, company=company)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(204, None)


@router.get(
    "/people/{uuid:person_id}/contact-methods/",
    auth=office_auth,
    operation_id="people_contact_methods_list",
    response=list[ContactMethodOut],
    tags=["people"],
)
def people_contact_methods_list(request: HttpRequest, person_id: UUID) -> list[ContactMethodData]:
    """List a Person's contact methods."""
    person = get_object_or_404(Person, id=person_id)
    methods = person.contact_methods.order_by("method_type", "-is_primary", "label", "value")
    return [contact_method_data(method) for method in methods]


@router.post(
    "/people/{uuid:person_id}/contact-methods/",
    auth=office_auth,
    operation_id="people_contact_methods_create",
    response={201: ContactMethodOut},
    tags=["people"],
)
def people_contact_methods_create(
    request: HttpRequest, person_id: UUID, payload: PersonContactMethodWriteRequest
) -> Status[ContactMethodData]:
    """Create a Person contact method (source=local)."""
    person = get_object_or_404(Person, id=person_id)
    data: ContactMethodWriteData = {
        "company": None,
        "person": person.id,
        "method_type": payload.method_type,
        "value": payload.value,
        "label": payload.label,
        "is_primary": payload.is_primary,
        "source": ContactMethod.Source.LOCAL,
    }
    try:
        method = save_contact_method(data)
    except (DjangoValidationError, ValueError) as exc:
        raise HttpError(400, validation_message(exc)) from exc
    return Status(201, contact_method_data(method))


@router.patch(
    "/people/{uuid:person_id}/contact-methods/{uuid:method_id}/",
    auth=office_auth,
    operation_id="people_contact_methods_partial_update",
    response=ContactMethodOut,
    tags=["people"],
)
def people_contact_methods_partial_update(
    request: HttpRequest,
    person_id: UUID,
    method_id: UUID,
    payload: PatchedPersonContactMethodWriteRequest,
) -> ContactMethodData:
    """Update one Person contact method (owner cannot change)."""
    method = get_object_or_404(ContactMethod, id=method_id, person_id=person_id)
    supplied = payload.model_dump(exclude_unset=True)
    data: ContactMethodWriteData = {}
    if "method_type" in supplied:
        data["method_type"] = payload.method_type
    if "value" in supplied:
        data["value"] = payload.value
    if "label" in supplied:
        data["label"] = payload.label
    if "is_primary" in supplied:
        data["is_primary"] = payload.is_primary
    try:
        updated = save_contact_method(data, instance=method)
    except (DjangoValidationError, ValueError) as exc:
        raise HttpError(400, validation_message(exc)) from exc
    return contact_method_data(updated)


@router.delete(
    "/people/{uuid:person_id}/contact-methods/{uuid:method_id}/",
    auth=office_auth,
    operation_id="people_contact_methods_destroy",
    response={204: None},
    tags=["people"],
)
def people_contact_methods_destroy(
    request: HttpRequest, person_id: UUID, method_id: UUID
) -> Status[None]:
    """Delete one Person contact method."""
    method = get_object_or_404(ContactMethod, id=method_id, person_id=person_id)
    delete_contact_method(method)
    return Status(204, None)


# ── Data quality (company-domain report; v1 job app URL kept) ────────────


@router.get(
    "/job/data-quality/duplicate-phones/",
    auth=office_auth,
    operation_id="check_duplicate_phones",
    response=DuplicatePhonesResponse,
    summary="Check duplicate phone ownership",
    tags=["Data Quality"],
)
def check_duplicate_phones(request: HttpRequest) -> DuplicatePhonesReport:
    """List numbers owned by multiple companies or colliding with internal lines."""
    return DuplicatePhoneReportService().get_report()


@router.get(
    "/job/data-quality/duplicate-identities/",
    auth=office_auth,
    operation_id="check_duplicate_identities",
    response=DuplicateIdentitiesResponse,
    summary="Check for duplicate companies and people",
    tags=["Data Quality"],
)
def check_duplicate_identities(request: HttpRequest) -> DuplicateIdentityReport:
    """List compact groups of Company and Person identities to merge or review."""
    return DuplicateIdentityReportService().get_report()
