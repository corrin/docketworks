"""Company REST service layer.

All business logic for the ``/api/companies/`` endpoints lives here; the ninja
router in ``apps/company/api.py`` is a thin translator.

Company creation and Xero-synced updates go through the accounting provider
registry (ADR 0012): duplicate check and push first, so local state never
diverges from Xero silently.

Company code cannot import the ``apps.search`` integration layer. It emits a
structured ``company_search`` log; the search integration owns persistence.
"""

import json
import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, QuerySet, When
from django.http import HttpRequest
from django.utils import timezone

from apps.accounting.registry import get_provider
from apps.company.models import Company, ContactMethod, SupplierPickupAddress
from apps.company.services.contact_methods import (
    clear_company_primary_phone,
    set_primary_phone,
)
from apps.core.errors import AppErrorContext, ConflictError, persist_app_error

if TYPE_CHECKING:
    from django_stubs_ext import WithAnnotations

COMPANY_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")


class DuplicateContactError(ConflictError):
    """The accounting provider already holds a contact with this name.

    Typed (rather than v1's parse-the-message-back-out-of-str(exc)) so the
    shared application boundary maps it to 409 without string surgery.
    """

    def __init__(self, name: str, external_id: str | None) -> None:
        """Carry the duplicate's identity so the endpoint can report it."""
        super().__init__(f"Company '{name}' already exists in the accounting provider")
        self.name = name
        self.external_id = external_id


class ProviderAuthRequiredError(ValueError):
    """The accounting provider has no valid token; connect before writing."""

    def __init__(self) -> None:
        """Use the fixed message; the endpoint maps this type to 401."""
        super().__init__("Accounting provider authentication required")


class CompanyPhoneAnnotations(TypedDict):
    """Queryset annotation required by the formatters; not a Company model field."""

    phone: str


if TYPE_CHECKING:
    # Evaluated only by the type checker (annotation is quoted at use site), so
    # the dev-only django_stubs_ext dependency is never imported at runtime.
    _AnnotatedCompanyWithPhone = WithAnnotations[Company, CompanyPhoneAnnotations]

logger = logging.getLogger(__name__)
company_search_logger = logging.getLogger("company_search")


class CompanyNameData(TypedDict):
    """id + name row for dropdowns."""

    id: str
    name: str


class CompanySummaryData(TypedDict):
    """Data contract for CompanySummaryData."""

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
    total_spend: float


class CompanyDetailData(TypedDict):
    """Data contract for CompanyDetailData."""

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
    total_spend: float


class CompanySearchPage(TypedDict):
    """Data contract for CompanySearchPage."""

    results: list[CompanySummaryData]
    count: int
    page: int
    page_size: int
    total_pages: int


class CompanyJobCompanyData(TypedDict):
    """Company reference embedded in a job header row."""

    id: str
    name: str


class CompanyJobHeaderData(TypedDict):
    """Data contract for CompanyJobHeaderData."""

    job_id: str
    job_number: int
    name: str
    company: CompanyJobCompanyData | None
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


class CompanyUpdateData(TypedDict, total=False):
    """Validated company update payload (v1 CompanyUpdateSerializer fields).

    ``phone`` is stored as the company's primary ContactMethod, never a
    Company column; presence of the key (even ``None``/blank) drives the
    clear-vs-leave-untouched semantics, so callers must pass only keys the
    client actually supplied.
    """

    name: str
    email: str | None
    phone: str | None
    address: str
    is_account_customer: bool
    allow_jobs: bool


class CompanyCreateData(TypedDict):
    """Validated company creation payload."""

    name: str
    email: NotRequired[str | None]
    phone: NotRequired[str | None]
    address: NotRequired[str | None]
    is_account_customer: bool
    allow_jobs: bool


def _date_to_datetime(date_obj: date | None) -> datetime | None:
    """Convert a date to a tz-aware midnight datetime."""
    if date_obj is None:
        return None
    return datetime.combine(date_obj, datetime.min.time(), tzinfo=timezone.get_current_timezone())


def annotated_with_phone(company: Company) -> "_AnnotatedCompanyWithPhone":
    """Vouch that the ``phone`` annotation is present on a fetched Company.

    The custom ``CompanyQuerySet`` erases ``WithAnnotations`` typing through
    ``annotate()``, so the formatters' annotated parameter type cannot be
    inferred; this validates the annotation actually exists before casting.
    """
    if "phone" not in company.__dict__:
        raise RuntimeError("caller must annotate ContactMethod.primary_phone_annotation as 'phone'")
    return cast("_AnnotatedCompanyWithPhone", company)


class CompanyRestService:
    """Service layer for Company REST operations."""

    @staticmethod
    def get_all_companies() -> list[CompanyNameData]:
        """Return all companies (id + name only) for fast dropdowns."""
        companies = Company.objects.all().order_by("name")
        return [{"id": str(company.id), "name": company.name} for company in companies]

    @staticmethod
    def search_companies(query: str, limit: int = 10) -> list[CompanySummaryData]:
        """Search job-eligible companies by name (min 3 chars, capped at 50 rows)."""
        try:
            if not query or len(query.strip()) < 3:
                return []

            query = query.strip()
            limit = max(1, min(limit, 50))

            companies = CompanyRestService._execute_company_search(query, limit)
            return CompanyRestService._format_company_search_results(companies)
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(additional_context={"query": query, "limit": limit}),
            )
            raise

    @staticmethod
    def list_companies(
        query: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> CompanySearchPage:
        """List companies with pagination, sorting, and optional ranked search."""
        try:
            # Validate sort field - whitelist allowed fields
            allowed_sort_fields = {
                "name": "name",
                "email": "email",
                "is_account_customer": "is_account_customer",
                "last_invoice_date": "last_invoice_date",
                "total_spend": "total_spend",
            }
            sort_field = allowed_sort_fields.get(sort_by, "name")
            if sort_dir.lower() == "desc":
                sort_field = f"-{sort_field}"

            # Merged tombstones are excluded: their data lives on the winner
            # (ADR 0034). They stay reachable by id on the detail endpoint.
            queryset = (
                Company.objects.with_invoice_summary()
                .filter(merged_into__isnull=True)
                .defer("raw_json")
                .annotate(
                    phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk")
                )
            )

            companies: list[Company]
            if query:
                ranked_ids = CompanyRestService._rank_matching_company_ids(
                    Company.objects.filter(merged_into__isnull=True), query
                )
                total_count = len(ranked_ids)
                offset = (page - 1) * page_size
                page_ids = ranked_ids[offset : offset + page_size]
                companies = CompanyRestService._hydrate_company_search_results(page_ids)
            else:
                total_count = queryset.count()
                offset = (page - 1) * page_size
                # Fable: "id" breaks ties so offset paging is a total order —
                # every uninvoiced company ties at total_spend 0.00 and names
                # are not unique, and without the tie-break page N+1 can repeat
                # or skip rows that page N already placed.
                companies = list(queryset.order_by(sort_field, "id")[offset : offset + page_size])

            total_pages = (total_count + page_size - 1) // page_size

            return {
                "results": CompanyRestService._format_company_search_results(companies),
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
        except ValueError:
            raise
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(
                    additional_context={
                        "query": query,
                        "page": page,
                        "page_size": page_size,
                    }
                ),
            )
            raise

    @staticmethod
    def get_company_by_id(company_id: UUID) -> CompanyDetailData:
        """Return full company details.

        Raises:
            ValueError: if the company does not exist.
        """
        try:
            company = (
                Company.objects.with_invoice_summary()
                .annotate(
                    phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk")
                )
                .get(id=company_id)
            )
            return CompanyRestService._format_company_detail(annotated_with_phone(company))
        except Company.DoesNotExist as exc:
            raise ValueError(f"Company with id {company_id} not found") from exc
        except ValueError:
            raise
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(
                    additional_context={
                        "operation": "get_company_by_id",
                        "company_id": str(company_id),
                    }
                ),
            )
            raise

    @staticmethod
    def create_company(data: CompanyCreateData) -> Company:
        """Create a company: provider duplicate check first, local write, then push.

        Raises:
            ValueError: validation failure, duplicate in the provider, no
                provider authentication, or a failed provider push (the local
                row is deleted again — a company must not exist locally
                without its Xero contact).
        """
        try:
            provider = get_provider()
            if not provider.get_valid_token():
                raise ProviderAuthRequiredError
            return CompanyRestService._create_company_in_xero(data)
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(
                    additional_context={
                        "operation": "create_company",
                        "payload_keys": list(data.keys()),
                    }
                ),
            )
            raise

    @staticmethod
    def _create_company_in_xero(company_data: CompanyCreateData) -> Company:
        """Create the company locally and as a provider contact."""
        provider = get_provider()
        name = company_data["name"]

        existing = provider.search_contact_by_name(name)
        if existing is not None:
            raise DuplicateContactError(name, existing.external_id)

        # Local write first, inside one transaction with the phone method, so
        # a phone conflict rolls the company back before anything is pushed.
        with transaction.atomic():
            company = Company.objects.create(
                name=name,
                email=company_data.get("email") or None,
                address=company_data.get("address") or None,
                is_account_customer=company_data["is_account_customer"],
                allow_jobs=company_data["allow_jobs"],
                xero_last_modified=timezone.now(),
            )
            CompanyRestService._apply_company_phone_change(
                company,
                phone_supplied="phone" in company_data,
                raw_phone=company_data.get("phone"),
            )

        # Push to the provider (persists xero_contact_id on the company).
        result = provider.create_contact(company)
        if not result.success:
            company_id = company.id
            company.delete()
            logger.warning(
                "Deleted local company after accounting provider create failure",
                extra={
                    "company_id": str(company_id),
                    "company_name": name,
                    "provider": provider.provider_name,
                    "operation": "create_company_in_xero_cleanup",
                },
            )
            raise ValueError(
                f"Failed to create company in {provider.provider_name}: {result.error}"
            )

        logger.info(
            "Company %s created locally and in %s",
            company.id,
            provider.provider_name,
            extra={
                "company_id": str(company.id),
                "company_name": company.name,
                "xero_contact_id": company.xero_contact_id,
                "operation": "create_company_in_xero",
            },
        )
        return company

    @staticmethod
    def update_company(company_id: UUID, data: CompanyUpdateData) -> "_AnnotatedCompanyWithPhone":
        """Update a company; a Xero-synced one (``xero_contact_id`` set) also pushes.

        The provider token is checked before the local write, so an
        unauthenticated install fails before anything changes — a local edit
        that silently skipped the push would diverge from Xero.

        Raises:
            ValueError: company not found, or validation failure.
            RuntimeError: provider unauthenticated, or the provider push failed
                (the local write is already committed in that case, matching
                v1: the next sync reconciles from local, which is newer).
        """
        try:
            company = Company.objects.filter(id=company_id).first()
            if company is None:
                raise ValueError(f"Company with id {company_id} not found")

            # Stored as the company's primary ContactMethod, not a Company
            # field, so it never reaches the setattr loop below.
            phone_supplied = "phone" in data
            phone = data.pop("phone", None)

            # v1's guard (`not data.get("name") and not company.name`) was dead
            # code — company.name is never blank on an existing row, so an
            # explicit {"name": ""} silently blanked the company. Reject it
            # (ledgered divergence; ultra review 2026-08-02).
            if "name" in data and not data["name"]:
                raise ValueError("Company name is required")

            if company.xero_contact_id and not get_provider().get_valid_token():
                raise ProviderAuthRequiredError

            with transaction.atomic():
                for field, value in data.items():
                    setattr(company, field, value)
                company.xero_last_modified = timezone.now()
                company.save()

                CompanyRestService._apply_company_phone_change(
                    company,
                    phone_supplied=phone_supplied,
                    raw_phone=phone,
                )

                logger.info(
                    "Company %s updated locally%s",
                    company.id,
                    " (Xero push follows)" if company.xero_contact_id else " (no Xero sync)",
                    extra={
                        "company_id": str(company.id),
                        "company_name": company.name,
                        "operation": "update_company_local",
                    },
                )

            # FIXME (ported from v1): `allow_jobs` is a local-only field (not
            # synced to Xero) but toggling it still routes through this path,
            # which unconditionally bumps `xero_last_modified` and pushes
            # below. That wastes Xero API quota and can fool the next sync
            # into thinking local state is newer than remote.
            if company.xero_contact_id:
                result = get_provider().update_contact(company)
                if not result.success:
                    raise RuntimeError(
                        f"Failed to update company in {get_provider().provider_name}: "
                        f"{result.error}"
                    )

            # The response's phone field always reads from a queryset annotation;
            # refetch through it, restoring the with_invoice_summary() aggregates
            # _format_company_detail needs.
            updated_with_phone = annotated_with_phone(
                Company.objects.with_invoice_summary()
                .annotate(
                    phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk")
                )
                .get(id=company.id)
            )
        except ValueError:
            raise
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(
                    additional_context={
                        "operation": "update_company",
                        "company_id": str(company_id),
                        "payload_keys": list(data.keys()),
                    }
                ),
            )
            raise
        else:
            return updated_with_phone

    @staticmethod
    def _apply_company_phone_change(
        company: Company,
        *,
        phone_supplied: bool,
        raw_phone: str | None,
    ) -> None:
        """Upsert/clear the primary phone; omitted input leaves methods untouched."""
        if not phone_supplied:
            logger.debug(
                "Company phone omitted; leaving contact methods unchanged",
                extra={
                    "company_id": str(company.id),
                    "operation": "company_phone_omitted",
                },
            )
            return

        if raw_phone is not None and raw_phone.strip():
            try:
                set_primary_phone(company, raw_phone)
            except DjangoValidationError as exc:
                raise ValueError("; ".join(exc.messages)) from exc
            else:
                return

        clear_company_primary_phone(company)

    # ── Ranked name search ───────────────────────────────────────────────

    @staticmethod
    def _execute_company_search(query: str, limit: int) -> list[Company]:
        ranked_ids = CompanyRestService._rank_matching_company_ids(
            Company.objects.filter(allow_jobs=True), query
        )
        return CompanyRestService._hydrate_company_search_results(ranked_ids[:limit])

    @staticmethod
    def _hydrate_company_search_results(company_ids: list[UUID]) -> list[Company]:
        if not company_ids:
            return []

        ordering = Case(
            *[
                When(id=company_id, then=position)
                for position, company_id in enumerate(company_ids)
            ],
            output_field=IntegerField(),
        )
        return list(
            Company.objects.with_invoice_summary()
            .defer("raw_json")  # Not needed for search results
            .annotate(phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk"))
            .only(
                "id",
                "name",
                "email",
                "address",
                "is_account_customer",
                "is_supplier",
                "allow_jobs",
                "xero_contact_id",
            )
            .filter(id__in=company_ids)
            .order_by(ordering)
        )

    @staticmethod
    def _rank_matching_company_ids(queryset: QuerySet[Company], query: str) -> list[UUID]:
        tokens = CompanyRestService._company_search_tokens(query)
        if not tokens:
            return []

        candidate_filter = CompanyRestService._company_name_candidate_filter(tokens)
        candidates = queryset.filter(candidate_filter).values_list("id", "name")

        ranked = [
            (
                CompanyRestService._company_name_score(name, query, tokens),
                company_id,
            )
            for company_id, name in candidates.iterator()
            if CompanyRestService._company_name_matches(name, tokens)
        ]
        # Fable: the id is the tie-break for equal scores; the candidate
        # queryset's name ordering alone leaves equal (score, name) pairs in
        # whatever order the database returned them, which offset paging
        # cannot rely on.
        ranked.sort(key=lambda item: (item[0], str(item[1])))
        return [company_id for _, company_id in ranked]

    @staticmethod
    def _company_search_tokens(query: str) -> list[str]:
        return COMPANY_SEARCH_TOKEN_RE.findall(query.lower())

    @staticmethod
    def _normalized_company_search_text(value: str) -> str:
        return " ".join(COMPANY_SEARCH_TOKEN_RE.findall(value.lower()))

    @staticmethod
    def _company_name_candidate_filter(tokens: list[str]) -> Q:
        candidate_filter = Q()
        for token in tokens:
            candidate_filter &= Q(name__icontains=token)
        return candidate_filter

    @staticmethod
    def _company_name_matches(name: str, tokens: list[str]) -> bool:
        name_tokens = CompanyRestService._company_search_tokens(name)
        return all(
            any(name_token.startswith(query_token) for name_token in name_tokens)
            for query_token in tokens
        )

    @staticmethod
    def _company_name_score(
        name: str, query: str, tokens: list[str]
    ) -> tuple[int, int, int, int, int, int, str]:
        normalized_name = CompanyRestService._normalized_company_search_text(name)
        normalized_query = CompanyRestService._normalized_company_search_text(query)
        name_tokens = CompanyRestService._company_search_tokens(name)

        if normalized_name == normalized_query:
            tier = 0
        elif normalized_name.startswith(normalized_query):
            tier = 1
        elif normalized_query in normalized_name:
            tier = 2
        else:
            tier = 3

        token_scores = [
            CompanyRestService._company_token_match_score(token, name_tokens) for token in tokens
        ]
        positions = [normalized_name.find(token) for token in tokens]
        ordered_penalty = 0 if positions == sorted(positions) else 1
        return (
            tier,
            max(token_scores),
            sum(token_scores),
            sum(positions),
            ordered_penalty,
            len(normalized_name),
            normalized_name,
        )

    @staticmethod
    def _company_token_match_score(query_token: str, name_tokens: list[str]) -> int:
        if query_token in name_tokens:
            return 0
        if any(token.startswith(query_token) for token in name_tokens):
            return 1
        return 99

    # ── Search logging ──

    @staticmethod
    def log_company_search_results(
        *,
        request: HttpRequest | None,
        source: str,
        query: str,
        companies: list[CompanySummaryData],
        total_count: int,
    ) -> None:
        """Emit the structured company_search log line (v1 behaviour).

        v1 also wrote a SearchTelemetryEvent row via ``apps.search``; domain
        apps may not import the search integration (layer contract), so that
        write returns with the search-app port.
        """
        if len(query.strip()) < 3:
            return

        tokens = CompanyRestService._company_search_tokens(query)
        user = getattr(request, "user", None) if request else None
        payload = {
            "event": "company_search_results",
            "search_id": str(uuid4()),
            "source": source,
            "query": query,
            "path": getattr(request, "path", None),
            "query_string": (request.META.get("QUERY_STRING", "") if request is not None else ""),
            "user_id": str(getattr(user, "id", "")) if user else None,
            "user_email": getattr(user, "office_email", None) if user else None,
            "result_count": total_count,
            "returned_count": len(companies),
            "results": [
                CompanyRestService._company_search_log_result(
                    rank=index + 1,
                    result=company,
                    query=query,
                    tokens=tokens,
                )
                for index, company in enumerate(companies)
            ],
        }
        company_search_logger.info(json.dumps(payload, sort_keys=True, default=str))

    @staticmethod
    def _company_search_log_result(
        *,
        rank: int,
        result: CompanySummaryData,
        query: str,
        tokens: list[str],
    ) -> dict[str, object]:
        company_name = result["name"]
        name_tokens = CompanyRestService._company_search_tokens(company_name)
        return {
            "rank": rank,
            "company_id": result["id"],
            "company_name": company_name,
            "search_score": CompanyRestService._company_name_score(company_name, query, tokens),
            "search_reasons": [
                {
                    "token": token,
                    "reason": CompanyRestService._company_token_match_reason(token, name_tokens),
                    "score": CompanyRestService._company_token_match_score(token, name_tokens),
                }
                for token in tokens
            ],
        }

    @staticmethod
    def _company_token_match_reason(query_token: str, name_tokens: list[str]) -> str:
        if query_token in name_tokens:
            return "token_exact"
        if any(token.startswith(query_token) for token in name_tokens):
            return "token_prefix"
        return "no_match"

    # ── Response formatting ──────────────────────────────────────────────

    @staticmethod
    def _format_company_summary(
        company: "_AnnotatedCompanyWithPhone",
    ) -> CompanySummaryData:
        """Format a single company summary for list/search responses.

        Callers must annotate their queryset with
        ContactMethod.primary_phone_annotation (see CompanyPhoneAnnotations).
        """
        return {
            "id": str(company.id),
            "name": company.name,
            "email": company.email or "",
            "phone": company.phone,
            "address": company.address or "",
            "is_account_customer": company.is_account_customer,
            "is_supplier": company.is_supplier,
            "allow_jobs": company.allow_jobs,
            "xero_contact_id": company.xero_contact_id or "",
            "last_invoice_date": _date_to_datetime(company.last_invoice_date),
            "total_spend": float(company.total_spend),
        }

    @staticmethod
    def _format_company_search_results(
        companies: list[Company],
    ) -> list[CompanySummaryData]:
        return [
            CompanyRestService._format_company_summary(annotated_with_phone(company))
            for company in companies
        ]

    @staticmethod
    def _format_company_detail(
        company: "_AnnotatedCompanyWithPhone",
    ) -> CompanyDetailData:
        """Format complete company details for API responses.

        Callers must annotate their queryset with
        ContactMethod.primary_phone_annotation (see CompanyPhoneAnnotations).
        """
        return {
            "id": str(company.id),
            "name": company.name,
            "email": company.email or "",
            "phone": company.phone,
            "address": company.address or "",
            "is_account_customer": company.is_account_customer,
            "is_supplier": company.is_supplier,
            "allow_jobs": company.allow_jobs,
            "xero_contact_id": company.xero_contact_id or "",
            "xero_tenant_id": company.xero_tenant_id or "",
            "xero_last_modified": company.xero_last_modified,
            "xero_last_synced": company.xero_last_synced,
            "xero_archived": company.xero_archived,
            "xero_merged_into_id": company.xero_merged_into_id or "",
            "merged_into": str(company.merged_into.id) if company.merged_into else None,
            "django_created_at": company.django_created_at,
            "django_updated_at": company.django_updated_at,
            "last_invoice_date": _date_to_datetime(company.last_invoice_date),
            "total_spend": float(company.total_spend),
        }

    @staticmethod
    def get_company_jobs(company_id: UUID) -> list[CompanyJobHeaderData]:
        """Return all jobs for a company as header rows (newest first).

        Raises:
            ValueError: if the company does not exist.
        """
        try:
            if not Company.objects.filter(id=company_id).exists():
                raise ValueError(f"Company with id {company_id} not found")

            # Function-level import: job imports company at module level, so a
            # module-level import here would create a cycle.
            from apps.job.models import Job  # noqa: PLC0415

            query_fields = ["id", "company_id", *Job.JOB_DIRECT_FIELDS]
            jobs = (
                Job.objects.filter(company_id=company_id)
                # quote joined in because job.quoted reads it per job below
                .select_related("company", "quote")
                .only(*query_fields, "quote__id")
                .order_by("-job_number")
            )

            return [
                {
                    "job_id": str(job.id),
                    "job_number": job.job_number,
                    "name": job.name,
                    "company": (
                        {"id": str(job.company.id), "name": job.company.name}
                        if job.company
                        else None
                    ),
                    "status": job.status,
                    "pricing_methodology": job.pricing_methodology,
                    "speed_quality_tradeoff": job.speed_quality_tradeoff,
                    "fully_invoiced": job.fully_invoiced,
                    "has_quote_in_xero": job.quoted,
                    "is_fixed_price": job.pricing_methodology == "fixed_price",
                    "quote_acceptance_date": job.quote_acceptance_date,
                    "paid": job.paid,
                    "rejected_flag": job.rejected_flag,
                    "min_people": job.min_people,
                    "max_people": job.max_people,
                }
                for job in jobs
            ]
        except ValueError:
            raise
        except Exception as exc:
            persist_app_error(exc)
            raise


# ── Supplier pickup addresses ───────────────────────────────────


class PickupAddressData(TypedDict):
    """v1 SupplierPickupAddressSerializer response row.

    Hoisted out of apps/company/api.py when the purchasing app became a second
    consumer: a PO detail embeds its pickup address (ADR 0039).
    """

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


def pickup_address_data(address: SupplierPickupAddress) -> PickupAddressData:
    """Serialise one pickup address."""
    return {
        "id": address.id,
        "company": address.company_id,
        "name": address.name,
        "street": address.street,
        "suburb": address.suburb,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
        "google_place_id": address.google_place_id,
        "latitude": float(address.latitude) if address.latitude is not None else None,
        "longitude": float(address.longitude) if address.longitude is not None else None,
        "is_primary": address.is_primary,
        "notes": address.notes,
        "is_active": address.is_active,
        "created_at": address.created_at,
        "updated_at": address.updated_at,
        "formatted_address": address.formatted_address,
    }
