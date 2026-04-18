"""
Client REST Service Layer

Following SRP (Single Responsibility Principle) and clean code guidelines.
All business logic for Client REST operations should be implemented here.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID

from django.db import transaction
from django.db.models import DecimalField, Max, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.client.models import Client, ClientContact
from apps.client.serializers import ClientCreateSerializer, ClientUpdateSerializer
from apps.client.utils import date_to_datetime
from apps.workflow.accounting.registry import get_provider
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import (
    persist_and_raise,
    persist_app_error,
)

logger = logging.getLogger(__name__)


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
                "phone": "phone",
                "is_account_customer": "is_account_customer",
                "last_invoice_date": "last_invoice_date",
                "total_spend": "total_spend",
            }
            sort_field = allowed_sort_fields.get(sort_by, "name")

            # Build ordering
            if sort_dir.lower() == "desc":
                sort_field = f"-{sort_field}"

            # Annotate computed fields for sorting capability
            # Note: mirrors Client.get_last_invoice_date() and get_total_spend()
            output = DecimalField(max_digits=12, decimal_places=2)
            queryset = Client.objects.annotate(
                last_invoice_date=Max("invoice__date"),
                total_spend=Coalesce(
                    Sum("invoice__total_excl_tax", output_field=output),
                    Value(Decimal("0.00")),
                    output_field=output,
                ),
            ).defer("raw_json")

            # Apply search filter if query provided
            if query:
                queryset = queryset.filter(name__icontains=query)

            # Get total count before pagination
            total_count = queryset.count()

            # Apply sorting and pagination
            offset = (page - 1) * page_size
            clients = queryset.order_by(sort_field)[offset : offset + page_size]

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
            client = Client.objects.get(id=client_id)
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
                    "phone": contact.phone,
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
                "phone": contact.phone,
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
        job_id: UUID, contact_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Updates the contact person for a specific job.

        Args:
            job_id: Job UUID
            contact_data: Contact data to update

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
                contact = ClientContact.objects.get(id=contact_id)
            except ClientContact.DoesNotExist:
                raise ValueError(f"Contact with id {contact_id} not found")

            # Validate contact belongs to the job's client
            if contact.client_id != job.client_id:
                raise ValueError("Contact does not belong to the job's client")

            # Update job's contact
            job.contact = contact
            job.save()

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
                "phone": contact.phone,
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
    def _execute_client_search(query: str, limit: int):
        """
        Executes client search with appropriate filters and annotations.
        """
        output = DecimalField(max_digits=12, decimal_places=2)

        return (
            Client.objects.filter(
                name__icontains=query
            )  # Case insensitive substring search
            .annotate(
                last_invoice_date=Max("invoice__date"),
                total_spend=Coalesce(
                    Sum(
                        "invoice__total_excl_tax",
                        output_field=output,
                    ),
                    Value(Decimal("0.00")),
                    output_field=output,
                ),
            )
            .defer("raw_json")  # Not needed for search results
            .only(
                "id",
                "name",
                "email",
                "phone",
                "address",
                "is_account_customer",
                "xero_contact_id",
            )
            .order_by("name")[:limit]
        )

    @staticmethod
    def _format_client_summary(client: Client) -> Dict[str, Any]:
        """
        Formats a single client summary for list/search responses.
        """
        # Use annotated values if available (from search queries), else use model methods
        last_invoice_date = (
            getattr(client, "last_invoice_date", None) or client.get_last_invoice_date()
        )
        total_spend = getattr(client, "total_spend", None)
        if total_spend is None:
            total_spend = client.get_total_spend()

        return {
            "id": str(client.id),
            "name": client.name,
            "email": client.email or "",
            "phone": client.phone or "",
            "address": client.address or "",
            "is_account_customer": client.is_account_customer,
            "is_supplier": client.is_supplier,
            "xero_contact_id": client.xero_contact_id or "",
            "last_invoice_date": date_to_datetime(last_invoice_date),
            "total_spend": f"${total_spend:,.2f}",
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
            "phone": client.phone or "",
            "address": client.address or "",
            "is_account_customer": client.is_account_customer,
            "is_supplier": client.is_supplier,
            "xero_contact_id": client.xero_contact_id or "",
            "xero_tenant_id": client.xero_tenant_id or "",
            "primary_contact_name": client.primary_contact_name or "",
            "primary_contact_email": client.primary_contact_email or "",
            "additional_contact_persons": client.additional_contact_persons or [],
            "all_phones": client.all_phones or [],
            "xero_last_modified": client.xero_last_modified,
            "xero_last_synced": client.xero_last_synced,
            "xero_archived": client.xero_archived,
            "xero_merged_into_id": client.xero_merged_into_id or "",
            "merged_into": str(client.merged_into.id) if client.merged_into else None,
            "django_created_at": client.django_created_at,
            "django_updated_at": client.django_updated_at,
            "last_invoice_date": date_to_datetime(client.get_last_invoice_date()),
            "total_spend": f"${client.get_total_spend():,.2f}",
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
                phone=client_data.get("phone") or "",
                address=client_data.get("address") or "",
                is_account_customer=client_data.get("is_account_customer", True),
                xero_last_modified=timezone.now(),
            )

        # Push to accounting provider (persists xero_contact_id on the client object)
        result = provider.create_contact(client)
        if not result.success:
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
            client.phone = data.get("phone", client.phone)
            client.address = data.get("address", client.address)
            client.is_account_customer = data.get(
                "is_account_customer", client.is_account_customer
            )
            client.xero_last_modified = timezone.now()
            client.save()

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
                .select_related("client")
                .only(*query_fields)
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
