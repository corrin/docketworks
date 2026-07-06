"""
Company REST Service Layer

Following SRP (Single Responsibility Principle) and clean code guidelines.
All business logic for Company REST operations should be implemented here.
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from apps.accounts.models import Staff

from django.db import transaction
from django.db.models import Case, IntegerField, Q, When
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.company.models import ClientContact, Company
from apps.company.serializers import CompanyCreateSerializer, CompanyUpdateSerializer
from apps.company.utils import date_to_datetime
from apps.workflow.accounting.registry import get_provider
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import (
    persist_and_raise,
    persist_app_error,
)
from apps.workflow.services.search_telemetry import SearchTelemetryService

COMPANY_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")

logger = logging.getLogger(__name__)
company_search_logger = logging.getLogger("company_search")


class CompanyRestService:
    """
    Service layer for Company REST operations.
    Implements all business rules related to Company manipulation via REST API.
    """

    @staticmethod
    def get_all_companies() -> List[Dict[str, Any]]:
        """
        Retrieves all companies with basic information for dropdowns.

        Returns:
            List of company dictionaries with id and name
        """
        try:
            companies = Company.objects.all().order_by("name")
            return [
                {
                    "id": str(company.id),
                    "name": company.name,
                }
                for company in companies
            ]
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(exc)

    @staticmethod
    def search_companies(query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Searches companies by name with enhanced data.

        Args:
            query: Search query (minimum 3 characters)
            limit: Maximum results to return (capped at 50)

        Returns:
            List of company dictionaries with detailed information

        Raises:
            ValueError: If query is too short
        """
        try:
            # Guard clause - validate query length
            if not query or len(query.strip()) < 3:
                return []

            # Sanitize and limit
            query = query.strip()
            limit = max(1, min(limit, 50))

            # Execute optimized search
            companies = CompanyRestService._execute_company_search(query, limit)
            return CompanyRestService._format_company_search_results(companies)

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(exc, additional_context={"query": query, "limit": limit})

    @staticmethod
    def list_companies(
        query: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> Dict[str, Any]:
        """
        Lists companies with pagination, sorting, and optional search.

        Args:
            query: Optional search query (min 3 chars for filtering)
            page: Page number (1-indexed)
            page_size: Results per page
            sort_by: Field to sort by
            sort_dir: Sort direction ('asc' or 'desc')

        Returns:
            Dict with results, count, page, page_size, total_pages
        """
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

            # Build ordering
            if sort_dir.lower() == "desc":
                sort_field = f"-{sort_field}"

            # Annotate computed fields for sorting capability
            queryset = Company.objects.with_invoice_summary().defer("raw_json")

            # Apply search filter if query provided
            if query:
                ranked_ids = CompanyRestService._rank_matching_company_ids(
                    Company.objects.all(), query
                )
                total_count = len(ranked_ids)
                offset = (page - 1) * page_size
                page_ids = ranked_ids[offset : offset + page_size]
                companies = CompanyRestService._hydrate_company_search_results(page_ids)
            else:
                ordering = (sort_field,)
                # Get total count before pagination
                total_count = queryset.count()

                # Apply sorting and pagination
                offset = (page - 1) * page_size
                companies = queryset.order_by(*ordering)[offset : offset + page_size]

            # Calculate total pages
            total_pages = (total_count + page_size - 1) // page_size

            return {
                "results": CompanyRestService._format_company_search_results(companies),
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "query": query,
                    "page": page,
                    "page_size": page_size,
                },
            )

    @staticmethod
    def get_company_by_id(company_id: UUID) -> Dict[str, Any]:
        """
        Retrieves a specific company by ID with full details.

        Args:
            company_id: Company UUID

        Returns:
            Dict with complete company information

        Raises:
            ValueError: If company not found
        """
        try:
            company = Company.objects.with_invoice_summary().get(id=company_id)
            return CompanyRestService._format_company_detail(company)
        except Company.DoesNotExist:
            raise ValueError(f"Company with id {company_id} not found")
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "get_company_by_id",
                    "company_id": str(company_id),
                },
            )

    @staticmethod
    def create_company(data: Dict[str, Any]) -> Company:
        """
        Creates a new company locally and in the accounting provider.

        Args:
            data: Company creation data

        Returns:
            Created Company instance

        Raises:
            ValueError: If validation fails or accounting provider sync fails
        """
        try:
            # Validate using DRF serializer
            serializer = CompanyCreateSerializer(data=data)
            if not serializer.is_valid():
                error_messages = []
                for field, errors in serializer.errors.items():
                    error_messages.extend([f"{field}: {e}" for e in errors])
                raise ValueError("; ".join(error_messages))

            # Check accounting provider authentication
            provider = get_provider()
            token = provider.get_valid_token()
            if not token:
                raise ValueError("Accounting provider authentication required")

            # Create in Xero first
            company = CompanyRestService._create_company_in_xero(
                serializer.validated_data
            )
            return company

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "create_company",
                    "payload_keys": list(data.keys()),
                },
            )

    @staticmethod
    def update_company(company_id: UUID, data: Dict[str, Any]) -> Company:
        """
        Updates an existing company.
        If company is synced with Xero, updates Xero first then syncs locally.

        Args:
            company_id: Company UUID
            data: Updated company data

        Returns:
            Updated Company instance

        Raises:
            ValueError: If company not found or validation fails
        """
        try:
            company = get_object_or_404(Company, id=company_id)

            # Store xero_contact_id before validation
            original_xero_contact_id = company.xero_contact_id

            # Validate using DRF serializer
            serializer = CompanyUpdateSerializer(data=data)
            if not serializer.is_valid():
                error_messages = []
                for field, errors in serializer.errors.items():
                    error_messages.extend([f"{field}: {e}" for e in errors])
                raise ValueError("; ".join(error_messages))

            validated_data = serializer.validated_data

            # Guard clause - validate required fields
            if not validated_data.get("name") and not company.name:
                raise ValueError("Company name is required")

            # DEBUG: Log company state after validation
            logger.info(
                f"Company data after validation: xero_contact_id={original_xero_contact_id}",
                extra={
                    "company_id": str(company.id),
                    "original_xero_contact_id": original_xero_contact_id,
                    "operation": "update_company_debug_after_validation",
                },
            )

            # Check if company is synced with Xero
            if original_xero_contact_id:
                # Update in Xero first, then sync locally
                updated_company = CompanyRestService._update_company_in_xero(
                    company, data
                )
                logger.info(
                    f"Company {updated_company.id} updated in Xero and synced locally",
                    extra={
                        "company_id": str(updated_company.id),
                        "company_name": updated_company.name,
                        "xero_contact_id": updated_company.xero_contact_id,
                        "operation": "update_company_xero_sync",
                    },
                )
                return updated_company
            else:
                # Local-only update for companies not synced with Xero
                with transaction.atomic():
                    for field, value in validated_data.items():
                        setattr(company, field, value)
                    company.xero_last_modified = timezone.now()
                    company.save()

                    logger.info(
                        f"Company {company.id} updated locally (no Xero sync)",
                        extra={
                            "company_id": str(company.id),
                            "company_name": company.name,
                            "operation": "update_company_local_only",
                        },
                    )

                return company

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "update_company",
                    "company_id": str(company_id),
                    "payload_keys": list(data.keys()),
                },
            )

    @staticmethod
    def get_company_contacts(company_id: UUID) -> List[Dict[str, Any]]:
        """
        Retrieves all contacts for a specific company.

        Args:
            company_id: Company UUID

        Returns:
            List of contact dictionaries

        Raises:
            ValueError: If company not found
        """
        try:
            company = get_object_or_404(Company, id=company_id)
            contacts = company.contacts.all().order_by("name")

            return [
                {
                    "id": str(contact.id),
                    "name": contact.name,
                    "email": contact.email,
                    "position": contact.position,
                    "is_primary": contact.is_primary,
                }
                for contact in contacts
            ]

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "get_company_contacts",
                    "company_id": str(company_id),
                },
            )

    @staticmethod
    def get_job_contact(job_id: UUID) -> Dict[str, Any]:
        """
        Retrieves contact information for a specific job.

        Args:
            job_id: Job UUID

        Returns:
            Dict with contact information

        Raises:
            ValueError: If job not found or no contact associated
        """
        # Import here to avoid circular imports
        from apps.job.models import Job

        try:
            job = Job.objects.select_related("contact").get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job with id {job_id} not found")
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "get_job_contact",
                    "job_id": str(job_id),
                },
            )

        if not job.contact:
            # Documented business validation failure should not be persisted
            raise ValueError(f"No contact associated with job {job_id}")

        contact = job.contact
        try:
            return {
                "id": str(contact.id),
                "name": contact.name,
                "email": contact.email,
                "position": contact.position,
                "is_primary": contact.is_primary,
                "notes": contact.notes,
            }
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "serialize_job_contact",
                    "job_id": str(job_id),
                },
            )

    @staticmethod
    def update_job_contact(
        job_id: UUID, contact_data: Dict[str, Any], user: "Staff"
    ) -> Dict[str, Any]:
        """
        Updates the contact person for a specific job.

        Args:
            job_id: Job UUID
            contact_data: Contact data to update
            user: Staff performing the update

        Returns:
            Dict with updated contact information

        Raises:
            ValueError: If job not found, contact not found, or validation fails
        """
        try:
            # Import here to avoid circular imports
            from apps.job.models import Job

            try:
                job = Job.objects.select_related("company", "contact").get(id=job_id)
            except Job.DoesNotExist:
                raise ValueError(f"Job with id {job_id} not found")

            # Validate contact exists and belongs to the same company
            contact_id = contact_data.get("id")
            if not contact_id:
                raise ValueError("Contact ID is required")

            try:
                contact = ClientContact.objects.get(id=contact_id)
            except ClientContact.DoesNotExist:
                raise ValueError(f"Contact with id {contact_id} not found")

            # Validate contact belongs to the job's company
            if contact.company_id != job.company_id:
                raise ValueError("Contact does not belong to the job's company")

            # Update job's contact
            job.contact = contact
            job.save(staff=user)

            logger.info(
                f"Contact {contact_id} assigned to job {job_id}",
                extra={
                    "job_id": str(job_id),
                    "contact_id": str(contact_id),
                    "company_id": str(job.company_id),
                    "operation": "update_job_contact",
                },
            )

            return {
                "id": str(contact.id),
                "name": contact.name,
                "email": contact.email,
                "position": contact.position,
                "is_primary": contact.is_primary,
                "notes": contact.notes,
            }

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "update_job_contact",
                    "job_id": str(job_id),
                    "contact_id": contact_data.get("id"),
                },
            )

    @staticmethod
    def _execute_company_search(query: str, limit: int):
        """
        Executes company search with appropriate filters and annotations.
        """
        ranked_ids = CompanyRestService._rank_matching_company_ids(
            Company.objects.filter(allow_jobs=True), query
        )
        return CompanyRestService._hydrate_company_search_results(ranked_ids[:limit])

    @staticmethod
    def _hydrate_company_search_results(company_ids):
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
    def _rank_matching_company_ids(queryset, query: str):
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
        ranked.sort(key=lambda item: item[0])
        return [company_id for _, company_id in ranked]

    @staticmethod
    def _company_search_tokens(query: str) -> list[str]:
        return COMPANY_SEARCH_TOKEN_RE.findall(query.lower())

    @staticmethod
    def _normalized_company_search_text(value: str) -> str:
        return " ".join(COMPANY_SEARCH_TOKEN_RE.findall(value.lower()))

    @staticmethod
    def _company_name_candidate_filter(tokens: list[str]):
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
    def _company_name_score(name: str, query: str, tokens: list[str]):
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
            CompanyRestService._company_token_match_score(token, name_tokens)
            for token in tokens
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

    @staticmethod
    def explain_company_search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
        ranked_ids = CompanyRestService._rank_matching_company_ids(
            Company.objects.all(), query
        )
        companies = CompanyRestService._hydrate_company_search_results(
            ranked_ids[:limit]
        )
        tokens = CompanyRestService._company_search_tokens(query)
        return [
            CompanyRestService._company_search_log_result(
                rank=index + 1,
                result=company,
                query=query,
                tokens=tokens,
            )
            for index, company in enumerate(companies)
        ]

    @staticmethod
    def log_company_search_results(
        *,
        request: Optional[HttpRequest],
        source: str,
        query: str,
        companies,
        total_count: int,
    ) -> None:
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
            "query_string": (
                request.META.get("QUERY_STRING", "") if request is not None else ""
            ),
            "user_id": str(getattr(user, "id", "")) if user else None,
            "user_email": getattr(user, "email", None) if user else None,
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
        SearchTelemetryService.log_search(
            request=request,
            domain="client",
            source=source,
            query=query,
            result_count=total_count,
            returned_result_ids=[
                result["id"] if isinstance(result, dict) else result.id
                for result in companies
            ],
            metadata={"results": payload["results"][:100]},
        )

    @staticmethod
    def log_company_search_click(
        *,
        request: Optional[HttpRequest],
        source: str,
        query: str,
        company_id,
        rank: Optional[int],
    ) -> None:
        company = Company.objects.only("id", "name").get(id=company_id)
        user = getattr(request, "user", None) if request else None
        payload = {
            "event": "company_search_click",
            "search_id": str(uuid4()),
            "source": source,
            "query": query,
            "path": getattr(request, "path", None),
            "query_string": (
                request.META.get("QUERY_STRING", "") if request is not None else ""
            ),
            "user_id": str(getattr(user, "id", "")) if user else None,
            "user_email": getattr(user, "email", None) if user else None,
            "company_id": str(company.id),
            "company_name": company.name,
            "rank": rank,
        }
        company_search_logger.info(json.dumps(payload, sort_keys=True, default=str))
        SearchTelemetryService.log_click(
            request=request,
            domain="client",
            source=source,
            query=query,
            selected_result_id=str(company.id),
            selected_label=company.name,
            selected_rank=rank,
            metadata={"company_name": company.name},
        )

    @staticmethod
    def _company_search_log_result(
        *,
        rank: int,
        result: Company | Dict[str, Any],
        query: str,
        tokens: list[str],
    ) -> Dict[str, Any]:
        if isinstance(result, dict):
            company_id = result["id"]
            company_name = result["name"]
        else:
            company_id = str(result.id)
            company_name = result.name

        name_tokens = CompanyRestService._company_search_tokens(company_name)
        return {
            "rank": rank,
            "company_id": company_id,
            "company_name": company_name,
            "search_score": CompanyRestService._company_name_score(
                company_name, query, tokens
            ),
            "search_reasons": [
                {
                    "token": token,
                    "reason": CompanyRestService._company_token_match_reason(
                        token, name_tokens
                    ),
                    "score": CompanyRestService._company_token_match_score(
                        token, name_tokens
                    ),
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

    @staticmethod
    def _format_company_summary(company: Company) -> Dict[str, Any]:
        """
        Formats a single company summary for list/search responses.
        """
        return {
            "id": str(company.id),
            "name": company.name,
            "email": company.email or "",
            "address": company.address or "",
            "is_account_customer": company.is_account_customer,
            "is_supplier": company.is_supplier,
            "allow_jobs": company.allow_jobs,
            "xero_contact_id": company.xero_contact_id or "",
            "last_invoice_date": date_to_datetime(company.last_invoice_date),
            "total_spend": f"${company.total_spend:,.2f}",
        }

    @staticmethod
    def _format_company_search_results(companies) -> List[Dict[str, Any]]:
        """
        Formats company search results for API response.
        """
        return [
            CompanyRestService._format_company_summary(company) for company in companies
        ]

    @staticmethod
    def _format_company_detail(company: Company) -> Dict[str, Any]:
        """
        Formats complete company details for API response.
        """
        return {
            "id": str(company.id),
            "name": company.name,
            "email": company.email or "",
            "address": company.address or "",
            "is_account_customer": company.is_account_customer,
            "is_supplier": company.is_supplier,
            "allow_jobs": company.allow_jobs,
            "xero_contact_id": company.xero_contact_id or "",
            "xero_tenant_id": company.xero_tenant_id or "",
            "primary_contact_name": company.primary_contact_name or "",
            "primary_contact_email": company.primary_contact_email or "",
            "additional_contact_persons": company.additional_contact_persons or [],
            "xero_last_modified": company.xero_last_modified,
            "xero_last_synced": company.xero_last_synced,
            "xero_archived": company.xero_archived,
            "xero_merged_into_id": company.xero_merged_into_id or "",
            "merged_into": str(company.merged_into.id) if company.merged_into else None,
            "django_created_at": company.django_created_at,
            "django_updated_at": company.django_updated_at,
            "last_invoice_date": date_to_datetime(company.last_invoice_date),
            "total_spend": f"${company.total_spend:,.2f}",
        }

    @staticmethod
    def _create_company_in_xero(company_data: Dict[str, Any]) -> Company:
        """
        Creates company in the accounting provider and locally.
        """
        provider = get_provider()
        name = company_data["name"]

        # Check for duplicates in accounting provider
        existing = provider.search_contact_by_name(name)
        if existing is not None:
            raise ValueError(
                f"Company '{name}' already exists in {provider.provider_name}"
                f" with ID: {existing.external_id}"
            )

        # Create local company first
        with transaction.atomic():
            company = Company.objects.create(
                name=name,
                email=company_data.get("email") or "",
                address=company_data.get("address") or "",
                is_account_customer=company_data.get("is_account_customer", True),
                xero_last_modified=timezone.now(),
            )

        # Push to accounting provider (persists xero_contact_id on the company object)
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
            f"Company {company.id} created locally and in {provider.provider_name}",
            extra={
                "company_id": str(company.id),
                "company_name": company.name,
                "xero_contact_id": company.xero_contact_id,
                "operation": "create_company_in_xero",
            },
        )
        return company

    @staticmethod
    def _update_company_in_xero(company: Company, data: Dict[str, Any]) -> Company:
        """
        Updates company locally and in the accounting provider.
        """
        provider = get_provider()

        # Check accounting provider authentication
        token = provider.get_valid_token()
        if not token:
            raise ValueError("Accounting provider authentication required")

        # Update local fields first
        with transaction.atomic():
            company.name = data.get("name", company.name)
            company.email = data.get("email", company.email)
            company.address = data.get("address", company.address)
            company.is_account_customer = data.get(
                "is_account_customer", company.is_account_customer
            )
            if "allow_jobs" in data:
                company.allow_jobs = data["allow_jobs"]
            company.xero_last_modified = timezone.now()
            company.save()

        # FIXME: `allow_jobs` is a local-only field (not synced to Xero) but
        # toggling it still routes through this method, which unconditionally
        # bumps `xero_last_modified` and pushes to Xero below. That wastes
        # Xero API quota and -- more concerning -- can fool the next sync
        # into thinking local state is newer than remote, potentially
        # clobbering a genuine Xero-side change. Fix: either split into a
        # local-only `_update_company_locally` path for flags like
        # `allow_jobs`, or detect when `data` contains only local-only keys
        # and skip the push + timestamp bump.
        # Push updated company to accounting provider
        result = provider.update_contact(company)
        if not result.success:
            raise ValueError(
                f"Failed to update company in {provider.provider_name}: {result.error}"
            )

        logger.info(
            f"Company {company.id} updated locally and in {provider.provider_name}",
            extra={
                "company_id": str(company.id),
                "company_name": company.name,
                "xero_contact_id": company.xero_contact_id,
                "operation": "_update_company_in_xero",
            },
        )

        return company

    @staticmethod
    def get_company_jobs(company_id: UUID) -> List[Dict[str, Any]]:
        """
        Retrieves all jobs for a specific company.

        Args:
            company_id: Company UUID

        Returns:
            List of job header dictionaries

        Raises:
            ValueError: If company not found
        """
        try:
            # Guard clause - verify company exists
            if not Company.objects.filter(id=company_id).exists():
                raise ValueError(f"Company with id {company_id} not found")

            # Import here to avoid circular imports
            from apps.job.models import Job

            # Get all jobs for this company using JOB_DIRECT_FIELDS as source of truth
            query_fields = ["id", "company_id"] + Job.JOB_DIRECT_FIELDS
            jobs = (
                Job.objects.filter(company_id=company_id)
                # quote joined in because job.quoted reads it per job below
                .select_related("company", "quote")
                .only(*query_fields, "quote__id")
                .order_by("-job_number")
            )

            # Format job data
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

        except Exception as e:
            persist_app_error(e)
            raise
