import logging
import uuid

from django.db import models
from django.utils import timezone

from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


class Client(models.Model):
    # CHECKLIST - when adding a new field or property to Client, check these locations:
    #   1. CLIENT_DIRECT_FIELDS below (if it's a model field)
    #   2. _format_client_detail() in apps/client/services/client_rest_service.py
    #   3. _format_client_summary() in apps/client/services/client_rest_service.py (subset for lists)
    #   4. get_client_for_xero() in this file (Xero API format)
    #   5. update_client_from_raw_json() in apps/workflow/api/xero/reprocess_xero.py (Xero-sourced fields only)
    #   6. _update_client_in_xero() in apps/client/services/client_rest_service.py (Xero API format)
    #   7. ClientDetailResponseSerializer in apps/client/serializers.py
    #   8. ClientSearchResultSerializer in apps/client/serializers.py (subset for lists)
    #
    # Direct scalar model fields (not related objects, not properties).
    CLIENT_DIRECT_FIELDS = [
        "name",
        "email",
        "phone",
        "address",
        "is_account_customer",
        "is_supplier",
        "allow_jobs",
        "xero_contact_id",
        "xero_tenant_id",
        "primary_contact_name",
        "primary_contact_email",
        "additional_contact_persons",
        "all_phones",
        "xero_last_modified",
        "xero_last_synced",
        "xero_archived",
        "xero_merged_into_id",
    ]

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )  # Internal UUID
    xero_contact_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    xero_tenant_id = models.CharField(
        max_length=255, null=True, blank=True
    )  # For reference only - we are not fully multi-tenant yet
    # Optional because not all prospects are synced to Xero
    name = models.CharField(max_length=255, db_index=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    is_account_customer = models.BooleanField(
        default=False
    )  # Account vs cash customer flag
    is_supplier = models.BooleanField(
        default=False
    )  # Indicates if this client is also a supplier
    allow_jobs = models.BooleanField(
        default=True,
        help_text=(
            "If False, this client cannot be selected as the client on a Job. "
            "Use for Xero contacts that must exist (tax authorities, internal "
            "accounts, etc.) but should never appear on a job. Automatically "
            "set to False when a client is archived or merged in Xero."
        ),
    )
    xero_last_modified = models.DateTimeField(null=False, blank=False)

    raw_json = models.JSONField(
        null=True, blank=True
    )  # For debugging, stores the raw JSON from Xero

    # Fields for the primary contact person
    primary_contact_name = models.CharField(max_length=255, null=True, blank=True)
    primary_contact_email = models.EmailField(null=True, blank=True)

    # Store all contact persons from the Xero ContactPersons list
    additional_contact_persons = models.JSONField(null=True, blank=True, default=list)

    # Store all phone numbers from the Xero Phones list
    all_phones = models.JSONField(null=True, blank=True, default=list)

    django_created_at = models.DateTimeField(auto_now_add=True)
    django_updated_at = models.DateTimeField(auto_now=True)

    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)

    # Fields to track merged clients in Xero
    xero_archived = models.BooleanField(
        default=False,
        help_text="Indicates if this client has been archived/merged in Xero",
    )
    xero_merged_into_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="The Xero contact ID this client was merged into (temporary storage)",
    )
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_from_clients",
        help_text="The client this was merged into",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def validate_for_xero(self):
        """
        Validate if the client data is sufficient to sync to Xero.
        Only name is required by Xero.
        """
        if not self.name:
            logger.error(f"Client {self.id} does not have a valid name.")
            return False
        return True

    def get_last_invoice_date(self):
        """
        Get the date of the client's most recent invoice.
        """
        last_invoice = self.invoice_set.order_by("-date").first()
        return last_invoice.date if last_invoice else None

    def get_total_spend(self):
        """
        Calculate the total amount spent by the client (sum of all invoice totals).
        """
        return (
            self.invoice_set.aggregate(total=models.Sum("total_excl_tax"))["total"] or 0
        )

    def get_client_for_xero(self):
        """
        Return the client data in a format suitable for syncing to Xero.
        Handles None values explicitly to ensure proper serialization.
        """
        # Logging all data for debugging
        logger.debug(f"Preparing client for Xero sync: ID={self.id}, Name={self.name}")

        # Ensure required fields are present
        if not self.name:
            raise ValueError(
                f"Client {self.id} is missing a name, which is required for Xero."
            )

        # Prepare serialized data
        client_dict = {
            "contact_id": self.xero_contact_id or "",  # Empty string if None
            "name": self.name,  # Required by Xero, must not be None
            "email_address": self.email or "",  # Empty string if None
            "phones": [
                {
                    "phone_type": "DEFAULT",
                    "phone_number": self.phone or "",  # Empty string if None
                }
            ],
            "addresses": [
                {
                    "address_type": "STREET",
                    "attention_to": self.name,
                    "address_line1": self.address or "",  # Empty string if None
                }
            ],
            "is_customer": self.is_account_customer,  # Boolean, always valid
        }

        # Log the final serialized data
        logger.debug(f"Serialized client data for Xero: {client_dict}")
        return client_dict

    @classmethod
    def get_shop_client_id(cls) -> str:
        """
        Get the shop client ID. Enforces singleton pattern -
        exactly one shop client must exist.

        Returns:
            str: UUID of the shop client

        Raises:
            ValueError: If zero or multiple shop clients found,
                or if shop_client_name not configured
            RuntimeError: If CompanyDefaults singleton is violated
        """
        # Validate CompanyDefaults singleton
        company_count = CompanyDefaults.objects.count()
        if company_count == 0:
            raise ValueError(
                "No CompanyDefaults found - database not properly initialized"
            )
        elif company_count > 1:
            raise RuntimeError(
                f"Multiple CompanyDefaults found ({company_count}) - "
                f"singleton violated!"
            )

        company_defaults = CompanyDefaults.get_solo()

        # Require explicit shop_client_name configuration
        if not company_defaults.shop_client_name:
            raise ValueError(
                "CompanyDefaults.shop_client_name is not configured. "
                "Please set the exact name of your shop client."
            )

        shop_name = company_defaults.shop_client_name

        # Find shop clients with exact name match
        shop_clients = cls.objects.filter(name=shop_name)
        shop_count = shop_clients.count()

        if shop_count == 0:
            raise ValueError(f"No shop client found with name '{shop_name}'")
        elif shop_count > 1:
            raise RuntimeError(
                f"Multiple shop clients found ({shop_count}) with name "
                f"'{shop_name}' - singleton violated!"
            )

        shop_client = shop_clients.get()

        # Validate the shop client has proper Xero integration
        # Commented out for testing purposes
        # if not shop_client.xero_contact_id:
        #     raise ValueError(
        #         f"Shop client '{shop_name}' has no Xero contact ID - "
        #         f"not properly synced"
        #     )

        return str(shop_client.id)

    def get_final_client(self):
        """
        Follow the merge chain to get the final client.
        If this client was merged into another, return that client
        (following the chain).
        Otherwise return self.
        """
        current = self
        seen = {self.id}  # Prevent infinite loops

        while current.merged_into:
            if current.merged_into.id in seen:
                logger.warning(f"Circular merge chain detected for client {self.id}")
                break
            seen.add(current.merged_into.id)
            current = current.merged_into

        return current


class ClientContact(models.Model):
    """
    Represents a contact person for a client.
    This model stores contact information that was previously synced with Xero
    but is now managed entirely within our application.
    """

    # CHECKLIST - when adding a new field or property to ClientContact, check these locations:
    #   1. CLIENTCONTACT_API_FIELDS or CLIENTCONTACT_INTERNAL_FIELDS below (if it's a model field)
    #   2. ClientContactSerializer in apps/client/serializers.py (uses CLIENTCONTACT_API_FIELDS)
    #   3. ClientContactSerializer.to_internal_value() nullable_fields list (converts "" → None)
    #   4. JobContactResponseSerializer in apps/client/serializers.py (subset for job context)
    #   5. ClientContactViewSet in apps/client/views/client_contact_viewset.py (CRUD operations)
    #   6. Job.contact FK in apps/job/models/job.py (relationship to ClientContact)
    #   7. reprocess_xero.py in apps/workflow/api/xero/ (Xero sync creates contacts)
    #
    # Database fields exposed via API serializers
    CLIENTCONTACT_API_FIELDS = [
        "id",
        "client",
        "name",
        "email",
        "phone",
        "position",
        "is_primary",
        "notes",
        "is_active",
        "created_at",
        "updated_at",
    ]

    # No internal fields for ClientContact - all fields are exposed
    CLIENTCONTACT_INTERNAL_FIELDS = []

    # All ClientContact model fields (derived)
    CLIENTCONTACT_ALL_FIELDS = CLIENTCONTACT_API_FIELDS + CLIENTCONTACT_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="contacts",
        help_text="The client this contact belongs to",
    )
    name = models.CharField(max_length=255, help_text="Full name of the contact person")
    email = models.EmailField(
        null=True, blank=True, help_text="Email address of the contact"
    )
    phone = models.CharField(
        max_length=150, null=True, blank=True, help_text="Phone number of the contact"
    )
    position = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Job title if it's helpful - else leave blank",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Indicates if this is the primary contact for the client",
    )
    notes = models.TextField(
        null=True, blank=True, help_text="Additional notes about this contact"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Soft delete flag - inactive contacts are hidden from normal queries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "name"]
        verbose_name = "Client Contact"
        verbose_name_plural = "Client Contacts"
        constraints = [
            models.UniqueConstraint(
                fields=["client", "name"],
                name="unique_client_contact_name",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.client.name})"

    def save(self, *args, **kwargs):
        # If this contact is being set as primary, ensure no other contacts
        # for this client are marked as primary
        if self.is_primary:
            ClientContact.objects.filter(client=self.client, is_primary=True).exclude(
                id=self.id
            ).update(is_primary=False)
        super().save(*args, **kwargs)


class Supplier(Client):
    """
    A Supplier is simply a Client with additional semantics.
    """

    class Meta:
        proxy = True
        db_table = "client_client"


class SupplierPickupAddress(models.Model):
    """
    Represents a pickup/delivery address for a supplier or client.

    Despite the name, this model can be used for any Client - not just those
    marked as suppliers. Suppliers can have multiple pickup addresses, with
    one marked as primary. Useful for tracking warehouse locations, branch
    offices, or delivery points.
    """

    # CHECKLIST - when adding a new field or property to SupplierPickupAddress, check:
    #   1. SUPPLIERPICKUPADDRESS_API_FIELDS below (if it's a model field)
    #   2. SupplierPickupAddressSerializer in apps/client/serializers.py
    #   3. SupplierPickupAddressSerializer.to_internal_value() nullable_fields list
    #   4. SupplierPickupAddressViewSet in apps/client/views/supplier_pickup_address_viewset.py
    #   5. PurchaseOrder.pickup_address FK in apps/purchasing/models.py
    #   6. PurchaseOrderDetailSerializer in apps/purchasing/serializers.py
    #   7. PurchaseOrderPDFGenerator in apps/purchasing/services/purchase_order_pdf_service.py
    #
    # Database fields exposed via API serializers
    SUPPLIERPICKUPADDRESS_API_FIELDS = [
        "id",
        "client",
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
        "is_active",
        "created_at",
        "updated_at",
    ]

    # No internal fields for SupplierPickupAddress - all fields are exposed
    SUPPLIERPICKUPADDRESS_INTERNAL_FIELDS = []

    # All SupplierPickupAddress model fields (derived)
    SUPPLIERPICKUPADDRESS_ALL_FIELDS = (
        SUPPLIERPICKUPADDRESS_API_FIELDS + SUPPLIERPICKUPADDRESS_INTERNAL_FIELDS
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="pickup_addresses",
        help_text="The supplier this pickup address belongs to",
    )
    name = models.CharField(
        max_length=255,
        help_text="Friendly name for this address (e.g., 'Main Warehouse', 'City Branch')",
    )
    street = models.CharField(
        max_length=255,
        help_text="Street address including unit/suite number",
    )
    suburb = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Suburb or neighbourhood (e.g., Thorndon, Northcote Point)",
    )
    city = models.CharField(
        max_length=100, help_text="City (e.g., Wellington, Auckland)"
    )
    state = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="State or province",
    )
    postal_code = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Postal or ZIP code",
    )
    country = models.CharField(
        max_length=100,
        default="New Zealand",
        help_text="Country name",
    )
    google_place_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Google Place ID for this address",
    )
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Latitude coordinate",
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Longitude coordinate",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Indicates if this is the primary pickup address for the supplier",
    )
    notes = models.TextField(
        null=True,
        blank=True,
        help_text="Additional notes (e.g., opening hours, access instructions)",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Soft delete flag - inactive addresses are hidden from normal queries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "name"]
        verbose_name = "Supplier Pickup Address"
        verbose_name_plural = "Supplier Pickup Addresses"
        constraints = [
            models.UniqueConstraint(
                fields=["client", "name"],
                name="unique_supplier_pickup_address_name",
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.city} ({self.client.name})"

    @property
    def formatted_address(self) -> str:
        """Return a formatted single-line address string."""
        parts = [self.street]
        if self.suburb:
            parts.append(self.suburb)
        parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.postal_code:
            parts.append(self.postal_code)
        if self.country and self.country != "New Zealand":
            parts.append(self.country)
        return ", ".join(parts)

    def save(self, *args, **kwargs):
        # If this address is being set as primary, ensure no other addresses
        # for this client are marked as primary
        if self.is_primary:
            SupplierPickupAddress.objects.filter(
                client=self.client, is_primary=True
            ).exclude(id=self.id).update(is_primary=False)
        super().save(*args, **kwargs)


# Alias for SupplierPickupAddress - can be used for any client, not just suppliers
ClientDeliveryAddress = SupplierPickupAddress
