"""
Client REST Service Layer

Following SRP (Single Responsibility Principle) and clean code guidelines.
All business logic for Client REST operations should be implemented here.
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from django_stubs_ext import WithAnnotations

    from apps.accounts.models import Staff

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, When
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.client.models import Client, ClientContact, ClientContactMethod
from apps.client.serializers import (
    ClientCreateSerializer,
    ClientUpdateSerializer,
    set_primary_phone,
)
from apps.client.utils import date_to_datetime
from apps.workflow.accounting.registry import get_provider
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import (
    persist_and_raise,
    persist_app_error,
)
from apps.workflow.services.search_telemetry import SearchTelemetryService

CLIENT_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")


class _ClientSummaryAnnotations(TypedDict):
    """Queryset annotations required by _format_client_summary; not Client fields."""

    phone: str


if TYPE_CHECKING:
    # Evaluated only by the type checker (annotation is quoted at use site), so
    # the dev-only django_stubs_ext dependency is never imported at runtime.
    _AnnotatedClientSummary = WithAnnotations[Client, _ClientSummaryAnnotations]

logger = logging.getLogger(__name__)
client_search_logger = logging.getLogger("client_search")


class ClientRestService:
    """
    Service layer for Client REST operations.
    Implements all business rules related to Client manipulation via REST API.
    """

    @staticmethod
    def get_all_clients() -> List[Dict[str, Any]]:
        """
        Retrieves all clients with basic information for dropdowns.

        Returns:
            List of client dictionaries with id and name
        """
        try:
            clients = Client.objects.all().order_by("name")
            return [
                {
                    "id": str(client.id),
                    "name": client.name,
                }
                for client in clients
            ]
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(exc)

    @staticmethod
    def search_clients(query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Searches clients by name with enhanced data.

        Args:
            query: Search query (minimum 3 characters)
            limit: Maximum results to return (capped at 50)

        Returns:
            List of client dictionaries with detailed information

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
            clients = ClientRestService._execute_client_search(query, limit)
            return ClientRestService._format_client_search_results(clients)

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(exc, additional_context={"query": query, "limit": limit})

    @staticmethod
    def list_clients(
        query: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> Dict[str, Any]:
        """
        Lists clients with pagination, sorting, and optional search.

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
            queryset = (
                Client.objects.with_invoice_summary()
                .defer("raw_json")
                .annotate(
                    phone=ClientContactMethod.primary_phone_annotation(
                        owner="client", outer_ref="pk"
                    )
                )
            )

            # Apply search filter if query provided
            if query:
                ranked_ids = ClientRestService._rank_matching_client_ids(
                    Client.objects.all(), query
                )
                total_count = len(ranked_ids)
                offset = (page - 1) * page_size
                page_ids = ranked_ids[offset : offset + page_size]
                clients = ClientRestService._hydrate_client_search_results(page_ids)
            else:
                ordering = (sort_field,)
                # Get total count before pagination
                total_count = queryset.count()

                # Apply sorting and pagination
                offset = (page - 1) * page_size
                clients = queryset.order_by(*ordering)[offset : offset + page_size]

            # Calculate total pages
            total_pages = (total_count + page_size - 1) // page_size

            return {
                "results": ClientRestService._format_client_search_results(clients),
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
    def get_client_by_id(client_id: UUID) -> Dict[str, Any]:
        """
        Retrieves a specific client by ID with full details.

        Args:
            client_id: Client UUID

        Returns:
            Dict with complete client information

        Raises:
            ValueError: If client not found
        """
        try:
            client = Client.objects.with_invoice_summary().get(id=client_id)
            return ClientRestService._format_client_detail(client)
        except Client.DoesNotExist:
            raise ValueError(f"Client with id {client_id} not found")
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "get_client_by_id",
                    "client_id": str(client_id),
                },
            )

    @staticmethod
    def create_client(data: Dict[str, Any]) -> Client:
        """
        Creates a new client locally and in the accounting provider.

        Args:
            data: Client creation data

        Returns:
            Created Client instance

        Raises:
            ValueError: If validation fails or accounting provider sync fails
        """
        try:
            # Validate using DRF serializer
            serializer = ClientCreateSerializer(data=data)
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
            client = ClientRestService._create_client_in_xero(serializer.validated_data)
            return client

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "create_client",
                    "payload_keys": list(data.keys()),
                },
            )

    @staticmethod
    def update_client(client_id: UUID, data: Dict[str, Any]) -> Client:
        """
        Updates an existing client.
        If client is synced with Xero, updates Xero first then syncs locally.

        Args:
            client_id: Client UUID
            data: Updated client data

        Returns:
            Updated Client instance

        Raises:
            ValueError: If client not found or validation fails
        """
        try:
            client = get_object_or_404(Client, id=client_id)

            # Store xero_contact_id before validation
            original_xero_contact_id = client.xero_contact_id

            # Validate using DRF serializer
            serializer = ClientUpdateSerializer(data=data)
            if not serializer.is_valid():
                error_messages = []
                for field, errors in serializer.errors.items():
                    error_messages.extend([f"{field}: {e}" for e in errors])
                raise ValueError("; ".join(error_messages))

            validated_data = serializer.validated_data

            # Guard clause - validate required fields
            if not validated_data.get("name") and not client.name:
                raise ValueError("Client name is required")

            # DEBUG: Log client state after validation
            logger.info(
                f"Client data after validation: xero_contact_id={original_xero_contact_id}",
                extra={
                    "client_id": str(client.id),
                    "original_xero_contact_id": original_xero_contact_id,
                    "operation": "update_client_debug_after_validation",
                },
            )

            # Check if client is synced with Xero
            if original_xero_contact_id:
                # Update in Xero first, then sync locally
                updated_client = ClientRestService._update_client_in_xero(client, data)
                logger.info(
                    f"Client {updated_client.id} updated in Xero and synced locally",
                    extra={
                        "client_id": str(updated_client.id),
                        "client_name": updated_client.name,
                        "xero_contact_id": updated_client.xero_contact_id,
                        "operation": "update_client_xero_sync",
                    },
                )
                return updated_client
            else:
                # Local-only update for clients not synced with Xero
                with transaction.atomic():
                    for field, value in validated_data.items():
                        setattr(client, field, value)
                    client.xero_last_modified = timezone.now()
                    client.save()

                    logger.info(
                        f"Client {client.id} updated locally (no Xero sync)",
                        extra={
                            "client_id": str(client.id),
                            "client_name": client.name,
                            "operation": "update_client_local_only",
                        },
                    )

                return client

        except AlreadyLoggedException:
            raise
        except Exception as exc:
            persist_and_raise(
                exc,
                additional_context={
                    "operation": "update_client",
                    "client_id": str(client_id),
                    "payload_keys": list(data.keys()),
                },
            )

    @staticmethod
    def get_client_contacts(client_id: UUID) -> List[Dict[str, Any]]:
        """
        Retrieves all contacts for a specific client.

        Args:
            client_id: Client UUID

        Returns:
            List of contact dictionaries

        Raises:
            ValueError: If client not found
        """
        try:
            client = get_object_or_404(Client, id=client_id)
            contacts = client.contacts.all().order_by("name")

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
                    "operation": "get_client_contacts",
                    "client_id": str(client_id),
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
            job = (
                Job.objects.select_related("contact")
                .annotate(
                    contact_phone=ClientContactMethod.primary_phone_annotation(
                        owner="contact", outer_ref="contact_id"
                    )
                )
                .get(id=job_id)
            )
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
                "phone": job.contact_phone,
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
                job = Job.objects.select_related("client", "contact").get(id=job_id)
            except Job.DoesNotExist:
                raise ValueError(f"Job with id {job_id} not found")

            # Validate contact exists and belongs to the same client
            contact_id = contact_data.get("id")
            if not contact_id:
                raise ValueError("Contact ID is required")

            try:
                # primary_phone rides the fetch; the job-level annotation would
                # reflect the job's old contact, not the one being assigned.
                contact = ClientContact.objects.annotate(
                    primary_phone=ClientContactMethod.primary_phone_annotation(
                        owner="contact", outer_ref="pk"
                    )
                ).get(id=contact_id)
            except ClientContact.DoesNotExist:
                raise ValueError(f"Contact with id {contact_id} not found")

            # Validate contact belongs to the job's client
            if contact.client_id != job.client_id:
                raise ValueError("Contact does not belong to the job's client")

            # Update job's contact
            job.contact = contact
            job.save(staff=user)

            logger.info(
                f"Contact {contact_id} assigned to job {job_id}",
                extra={
                    "job_id": str(job_id),
                    "contact_id": str(contact_id),
                    "client_id": str(job.client_id),
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
                "phone": contact.primary_phone,
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
    def _execute_client_search(query: str, limit: int):
        """
        Executes client search with appropriate filters and annotations.
        """
        ranked_ids = ClientRestService._rank_matching_client_ids(
            Client.objects.filter(allow_jobs=True), query
        )
        return ClientRestService._hydrate_client_search_results(ranked_ids[:limit])

    @staticmethod
    def _hydrate_client_search_results(client_ids):
        if not client_ids:
            return []

        ordering = Case(
            *[
                When(id=client_id, then=position)
                for position, client_id in enumerate(client_ids)
            ],
            output_field=IntegerField(),
        )
        return list(
            Client.objects.with_invoice_summary()
            .defer("raw_json")  # Not needed for search results
            .annotate(
                phone=ClientContactMethod.primary_phone_annotation(
                    owner="client", outer_ref="pk"
                )
            )
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
            .filter(id__in=client_ids)
            .order_by(ordering)
        )

    @staticmethod
    def _rank_matching_client_ids(queryset, query: str):
        tokens = ClientRestService._client_search_tokens(query)
        if not tokens:
            return []

        candidate_filter = ClientRestService._client_name_candidate_filter(tokens)
        candidates = queryset.filter(candidate_filter).values_list("id", "name")

        ranked = [
            (
                ClientRestService._client_name_score(name, query, tokens),
                client_id,
            )
            for client_id, name in candidates.iterator()
            if ClientRestService._client_name_matches(name, tokens)
        ]
        ranked.sort(key=lambda item: item[0])
        return [client_id for _, client_id in ranked]

    @staticmethod
    def _client_search_tokens(query: str) -> list[str]:
        return CLIENT_SEARCH_TOKEN_RE.findall(query.lower())

    @staticmethod
    def _normalized_client_search_text(value: str) -> str:
        return " ".join(CLIENT_SEARCH_TOKEN_RE.findall(value.lower()))

    @staticmethod
    def _client_name_candidate_filter(tokens: list[str]):
        candidate_filter = Q()
        for token in tokens:
            candidate_filter &= Q(name__icontains=token)
        return candidate_filter

    @staticmethod
    def _client_name_matches(name: str, tokens: list[str]) -> bool:
        name_tokens = ClientRestService._client_search_tokens(name)
        return all(
            any(name_token.startswith(query_token) for name_token in name_tokens)
            for query_token in tokens
        )

    @staticmethod
    def _client_name_score(name: str, query: str, tokens: list[str]):
        normalized_name = ClientRestService._normalized_client_search_text(name)
        normalized_query = ClientRestService._normalized_client_search_text(query)
        name_tokens = ClientRestService._client_search_tokens(name)

        if normalized_name == normalized_query:
            tier = 0
        elif normalized_name.startswith(normalized_query):
            tier = 1
        elif normalized_query in normalized_name:
            tier = 2
        else:
            tier = 3

        token_scores = [
            ClientRestService._client_token_match_score(token, name_tokens)
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
    def _client_token_match_score(query_token: str, name_tokens: list[str]) -> int:
        if query_token in name_tokens:
            return 0
        if any(token.startswith(query_token) for token in name_tokens):
            return 1
        return 99

    @staticmethod
    def explain_client_search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
        ranked_ids = ClientRestService._rank_matching_client_ids(
            Client.objects.all(), query
        )
        clients = ClientRestService._hydrate_client_search_results(ranked_ids[:limit])
        tokens = ClientRestService._client_search_tokens(query)
        return [
            ClientRestService._client_search_log_result(
                rank=index + 1,
                result=client,
                query=query,
                tokens=tokens,
            )
            for index, client in enumerate(clients)
        ]

    @staticmethod
    def log_client_search_results(
        *,
        request: Optional[HttpRequest],
        source: str,
        query: str,
        clients,
        total_count: int,
    ) -> None:
        if len(query.strip()) < 3:
            return

        tokens = ClientRestService._client_search_tokens(query)
        user = getattr(request, "user", None) if request else None
        payload = {
            "event": "client_search_results",
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
            "returned_count": len(clients),
            "results": [
                ClientRestService._client_search_log_result(
                    rank=index + 1,
                    result=client,
                    query=query,
                    tokens=tokens,
                )
                for index, client in enumerate(clients)
            ],
        }
        client_search_logger.info(json.dumps(payload, sort_keys=True, default=str))
        SearchTelemetryService.log_search(
            request=request,
            domain="client",
            source=source,
            query=query,
            result_count=total_count,
            returned_result_ids=[
                result["id"] if isinstance(result, dict) else result.id
                for result in clients
            ],
            metadata={"results": payload["results"][:100]},
        )

    @staticmethod
    def log_client_search_click(
        *,
        request: Optional[HttpRequest],
        source: str,
        query: str,
        client_id,
        rank: Optional[int],
    ) -> None:
        client = Client.objects.only("id", "name").get(id=client_id)
        user = getattr(request, "user", None) if request else None
        payload = {
            "event": "client_search_click",
            "search_id": str(uuid4()),
            "source": source,
            "query": query,
            "path": getattr(request, "path", None),
            "query_string": (
                request.META.get("QUERY_STRING", "") if request is not None else ""
            ),
            "user_id": str(getattr(user, "id", "")) if user else None,
            "user_email": getattr(user, "email", None) if user else None,
            "client_id": str(client.id),
            "client_name": client.name,
            "rank": rank,
        }
        client_search_logger.info(json.dumps(payload, sort_keys=True, default=str))
        SearchTelemetryService.log_click(
            request=request,
            domain="client",
            source=source,
            query=query,
            selected_result_id=str(client.id),
            selected_label=client.name,
            selected_rank=rank,
            metadata={"client_name": client.name},
        )

    @staticmethod
    def _client_search_log_result(
        *,
        rank: int,
        result: Client | Dict[str, Any],
        query: str,
        tokens: list[str],
    ) -> Dict[str, Any]:
        if isinstance(result, dict):
            client_id = result["id"]
            client_name = result["name"]
        else:
            client_id = str(result.id)
            client_name = result.name

        name_tokens = ClientRestService._client_search_tokens(client_name)
        return {
            "rank": rank,
            "client_id": client_id,
            "client_name": client_name,
            "search_score": ClientRestService._client_name_score(
                client_name, query, tokens
            ),
            "search_reasons": [
                {
                    "token": token,
                    "reason": ClientRestService._client_token_match_reason(
                        token, name_tokens
                    ),
                    "score": ClientRestService._client_token_match_score(
                        token, name_tokens
                    ),
                }
                for token in tokens
            ],
        }

    @staticmethod
    def _client_token_match_reason(query_token: str, name_tokens: list[str]) -> str:
        if query_token in name_tokens:
            return "token_exact"
        if any(token.startswith(query_token) for token in name_tokens):
            return "token_prefix"
        return "no_match"

    @staticmethod
    def _format_client_summary(client: "_AnnotatedClientSummary") -> Dict[str, Any]:
        """
        Formats a single client summary for list/search responses.

        Callers must annotate their queryset with
        ClientContactMethod.primary_phone_annotation (see _ClientSummaryAnnotations).
        """
        return {
            "id": str(client.id),
            "name": client.name,
            "email": client.email or "",
            "phone": client.phone,
            "address": client.address or "",
            "is_account_customer": client.is_account_customer,
            "is_supplier": client.is_supplier,
            "allow_jobs": client.allow_jobs,
            "xero_contact_id": client.xero_contact_id or "",
            "last_invoice_date": date_to_datetime(client.last_invoice_date),
            "total_spend": f"${client.total_spend:,.2f}",
        }

    @staticmethod
    def _format_client_search_results(clients) -> List[Dict[str, Any]]:
        """
        Formats client search results for API response.
        """
        return [ClientRestService._format_client_summary(client) for client in clients]

    @staticmethod
    def _format_client_detail(client: Client) -> Dict[str, Any]:
        """
        Formats complete client details for API response.
        """
        return {
            "id": str(client.id),
            "name": client.name,
            "email": client.email or "",
            "address": client.address or "",
            "is_account_customer": client.is_account_customer,
            "is_supplier": client.is_supplier,
            "allow_jobs": client.allow_jobs,
            "xero_contact_id": client.xero_contact_id or "",
            "xero_tenant_id": client.xero_tenant_id or "",
            "primary_contact_name": client.primary_contact_name or "",
            "primary_contact_email": client.primary_contact_email or "",
            "additional_contact_persons": client.additional_contact_persons or [],
            "xero_last_modified": client.xero_last_modified,
            "xero_last_synced": client.xero_last_synced,
            "xero_archived": client.xero_archived,
            "xero_merged_into_id": client.xero_merged_into_id or "",
            "merged_into": str(client.merged_into.id) if client.merged_into else None,
            "django_created_at": client.django_created_at,
            "django_updated_at": client.django_updated_at,
            "last_invoice_date": date_to_datetime(client.last_invoice_date),
            "total_spend": f"${client.total_spend:,.2f}",
        }

    @staticmethod
    def _create_client_in_xero(client_data: Dict[str, Any]) -> Client:
        """
        Creates client in the accounting provider and locally.
        """
        provider = get_provider()
        name = client_data["name"]

        # Check for duplicates in accounting provider
        existing = provider.search_contact_by_name(name)
        if existing is not None:
            raise ValueError(
                f"Client '{name}' already exists in {provider.provider_name}"
                f" with ID: {existing.external_id}"
            )

        # Create local client first
        with transaction.atomic():
            client = Client.objects.create(
                name=name,
                email=client_data.get("email") or "",
                address=client_data.get("address") or "",
                is_account_customer=client_data.get("is_account_customer", True),
                xero_last_modified=timezone.now(),
            )
            phone = client_data.get("phone")
            if phone and phone.strip():
                try:
                    set_primary_phone(client, phone)
                except DjangoValidationError as exc:
                    # Roll back the client and skip the Xero push; the view
                    # surfaces the ownership-guard message as a 400.
                    raise ValueError("; ".join(exc.messages)) from exc
            else:
                pass  # no phone supplied: nothing to store

        # Push to accounting provider (persists xero_contact_id on the client object)
        result = provider.create_contact(client)
        if not result.success:
            client_id = client.id
            client.delete()
            logger.warning(
                "Deleted local client after accounting provider create failure",
                extra={
                    "client_id": str(client_id),
                    "client_name": name,
                    "provider": provider.provider_name,
                    "operation": "create_client_in_xero_cleanup",
                },
            )
            raise ValueError(
                f"Failed to create client in {provider.provider_name}: {result.error}"
            )

        logger.info(
            f"Client {client.id} created locally and in {provider.provider_name}",
            extra={
                "client_id": str(client.id),
                "client_name": client.name,
                "xero_contact_id": client.xero_contact_id,
                "operation": "create_client_in_xero",
            },
        )
        return client

    @staticmethod
    def _update_client_in_xero(client: Client, data: Dict[str, Any]) -> Client:
        """
        Updates client locally and in the accounting provider.
        """
        provider = get_provider()

        # Check accounting provider authentication
        token = provider.get_valid_token()
        if not token:
            raise ValueError("Accounting provider authentication required")

        # Update local fields first
        with transaction.atomic():
            client.name = data.get("name", client.name)
            client.email = data.get("email", client.email)
            client.address = data.get("address", client.address)
            client.is_account_customer = data.get(
                "is_account_customer", client.is_account_customer
            )
            if "allow_jobs" in data:
                client.allow_jobs = data["allow_jobs"]
            client.xero_last_modified = timezone.now()
            client.save()

        # FIXME: `allow_jobs` is a local-only field (not synced to Xero) but
        # toggling it still routes through this method, which unconditionally
        # bumps `xero_last_modified` and pushes to Xero below. That wastes
        # Xero API quota and -- more concerning -- can fool the next sync
        # into thinking local state is newer than remote, potentially
        # clobbering a genuine Xero-side change. Fix: either split into a
        # local-only `_update_client_locally` path for flags like
        # `allow_jobs`, or detect when `data` contains only local-only keys
        # and skip the push + timestamp bump.
        # Push updated client to accounting provider
        result = provider.update_contact(client)
        if not result.success:
            raise ValueError(
                f"Failed to update client in {provider.provider_name}: {result.error}"
            )

        logger.info(
            f"Client {client.id} updated locally and in {provider.provider_name}",
            extra={
                "client_id": str(client.id),
                "client_name": client.name,
                "xero_contact_id": client.xero_contact_id,
                "operation": "_update_client_in_xero",
            },
        )

        return client

    @staticmethod
    def get_client_jobs(client_id: UUID) -> List[Dict[str, Any]]:
        """
        Retrieves all jobs for a specific client.

        Args:
            client_id: Client UUID

        Returns:
            List of job header dictionaries

        Raises:
            ValueError: If client not found
        """
        try:
            # Guard clause - verify client exists
            if not Client.objects.filter(id=client_id).exists():
                raise ValueError(f"Client with id {client_id} not found")

            # Import here to avoid circular imports
            from apps.job.models import Job

            # Get all jobs for this client using JOB_DIRECT_FIELDS as source of truth
            query_fields = ["id", "client_id"] + Job.JOB_DIRECT_FIELDS
            jobs = (
                Job.objects.filter(client_id=client_id)
                # quote joined in because job.quoted reads it per job below
                .select_related("client", "quote")
                .only(*query_fields, "quote__id")
                .order_by("-job_number")
            )

            # Format job data
            return [
                {
                    "job_id": str(job.id),
                    "job_number": job.job_number,
                    "name": job.name,
                    "client": (
                        {"id": str(job.client.id), "name": job.client.name}
                        if job.client
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
