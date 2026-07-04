import logging
import re
import uuid
from collections.abc import Iterable
from decimal import Decimal

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, models
from django.db.models.base import ModelBase
from django.db.models.functions import Coalesce
from django.utils import timezone
from xero_python.accounting.models import Address, Contact, Phone

logger = logging.getLogger(__name__)


def _include_auto_now_update_field(kwargs, field_name: str) -> None:
    update_fields = kwargs.get("update_fields")
    if update_fields is None:
        return

    update_field_names = (
        [update_fields] if isinstance(update_fields, str) else list(update_fields)
    )
    if not update_field_names or field_name in update_field_names:
        return

    kwargs["update_fields"] = [*update_field_names, field_name]


def _augment_update_fields(
    update_fields: Iterable[str] | None, field_name: str
) -> list[str] | None:
    """Add ``field_name`` to a partial ``update_fields`` so an auto-now column is saved."""
    if update_fields is None:
        return None
    names = [update_fields] if isinstance(update_fields, str) else list(update_fields)
    if names and field_name not in names:
        names.append(field_name)
    return names


class ClientQuerySet(models.QuerySet):
    """Custom queryset for Client with precomputed invoice aggregates."""

    def with_invoice_summary(self):
        output = models.DecimalField(max_digits=12, decimal_places=2)
        return self.annotate(
            last_invoice_date=models.Max("invoice__date"),
            total_spend=Coalesce(
                models.Sum("invoice__total_excl_tax", output_field=output),
                models.Value(Decimal("0.00")),
                output_field=output,
            ),
        )


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

    objects = ClientQuerySet.as_manager()

    # Direct scalar model fields (not related objects, not properties).
    CLIENT_DIRECT_FIELDS = [
        "name",
        "email",
        "address",
        "is_account_customer",
        "is_supplier",
        "allow_jobs",
        "xero_contact_id",
        "xero_tenant_id",
        "primary_contact_name",
        "primary_contact_email",
        "additional_contact_persons",
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
        indexes = [
            GinIndex(
                SearchVector("name", config="english"),
                name="client_name_fts_idx",
            ),
            GinIndex(
                fields=["name"],
                name="client_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        _include_auto_now_update_field(kwargs, "django_updated_at")
        super().save(*args, **kwargs)

    def validate_for_xero(self):
        """
        Validate if the client data is sufficient to sync to Xero.
        Only name is required by Xero.
        """
        if not self.name:
            logger.error(f"Client {self.id} does not have a valid name.")
            return False
        return True

    @property
    def last_invoice_date(self):
        if "_last_invoice_date" not in self.__dict__:
            raise RuntimeError(
                "Client.last_invoice_date requires "
                "Client.objects.with_invoice_summary()."
            )
        return self.__dict__["_last_invoice_date"]

    @last_invoice_date.setter
    def last_invoice_date(self, value):
        self.__dict__["_last_invoice_date"] = value

    @property
    def total_spend(self):
        if "_total_spend" not in self.__dict__:
            raise RuntimeError(
                "Client.total_spend requires Client.objects.with_invoice_summary()."
            )
        return self.__dict__["_total_spend"]

    @total_spend.setter
    def total_spend(self, value):
        self.__dict__["_total_spend"] = value

    def get_client_for_xero(self):
        """
        Build a xero_python.accounting.models.Contact for syncing to Xero.

        Returns an SDK model instance (not a dict) so the SDK's attribute_map
        translates Python snake_case to Xero's PascalCase wire format. Raw
        dicts ship verbatim and Xero silently drops every non-Name field.
        """
        if not self.name:
            raise ValueError(
                f"Client {self.id} is missing a name, which is required for Xero."
            )

        primary_phone = self.primary_phone_value()

        return Contact(
            contact_id=self.xero_contact_id,
            name=self.name,
            email_address=self.email,
            phones=[
                Phone(
                    phone_type="DEFAULT",
                    phone_number=primary_phone or None,
                )
            ],
            addresses=[
                Address(
                    address_type="STREET",
                    attention_to=self.name,
                    address_line1=self.address,
                )
            ],
            is_customer=self.is_account_customer,
        )

    def primary_phone_value(self) -> str:
        """The client's own primary phone number, or "" when it has none.

        Uses the same ordering as every other primary-phone consumer:
        primary first, then label/value as a stable tie-break.
        """
        method = (
            self.contact_methods.filter(
                method_type=ClientContactMethod.MethodType.PHONE
            )
            .order_by("-is_primary", "label", "value")
            .first()
        )
        return method.value if method else ""

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

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        update_fields = _augment_update_fields(update_fields, "updated_at")

        # If this contact is being set as primary, ensure no other contacts
        # for this client are marked as primary
        if self.is_primary:
            ClientContact.objects.filter(client=self.client, is_primary=True).exclude(
                id=self.id
            ).update(is_primary=False)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class PhoneAssignmentConflictError(Exception):
    """A phone number cannot be assigned to the proposed client/contact owner.

    ``conflict`` is the existing :class:`ClientContactMethod` owned by a
    different effective client, or ``None`` when the number is an active
    internal :class:`~apps.crm.models.PhoneEndpoint`.
    """

    def __init__(self, conflict: "ClientContactMethod | None") -> None:
        self.conflict = conflict
        if conflict is None:
            message = "phone number is an active internal phone endpoint"
        else:
            message = f"phone number already belongs to {conflict.owner_display_name()}"
        super().__init__(message)


class ClientContactMethod(models.Model):
    """Phone or email address owned by a client or one of its contacts."""

    class MethodType(models.TextChoices):
        PHONE = "phone", "Phone"
        EMAIL = "email", "Email"

    class Source(models.TextChoices):
        IMPORTED = "imported", "Imported"
        LOCAL = "local", "Local"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="contact_methods",
    )
    contact = models.ForeignKey(
        ClientContact,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="contact_methods",
    )
    method_type = models.CharField(max_length=20, choices=MethodType.choices)
    value = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=255, db_index=True)
    label = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.LOCAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["method_type", "-is_primary", "label", "value"]
        verbose_name = "Client Contact Method"
        verbose_name_plural = "Client Contact Methods"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(client__isnull=False, contact__isnull=True)
                    | models.Q(client__isnull=True, contact__isnull=False)
                ),
                name="client_contact_method_one_owner",
            ),
            models.UniqueConstraint(
                fields=["client", "method_type", "normalized_value"],
                condition=models.Q(client__isnull=False, contact__isnull=True),
                name="unique_client_contact_method_value",
            ),
            models.UniqueConstraint(
                fields=["contact", "method_type", "normalized_value"],
                condition=models.Q(client__isnull=True, contact__isnull=False),
                name="unique_contact_contact_method_value",
            ),
            models.UniqueConstraint(
                fields=["client", "method_type"],
                condition=models.Q(
                    client__isnull=False,
                    contact__isnull=True,
                    is_primary=True,
                ),
                name="unique_client_primary_contact_method",
            ),
            models.UniqueConstraint(
                fields=["contact", "method_type"],
                condition=models.Q(
                    client__isnull=True,
                    contact__isnull=False,
                    is_primary=True,
                ),
                name="unique_contact_primary_contact_method",
            ),
        ]

    def __str__(self) -> str:
        owner = self.contact or self.client
        return f"{self.method_type}: {self.value} ({owner})"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        update_fields = _augment_update_fields(update_fields, "updated_at")
        # Resolve the target database the way Model.save() does, so the guard
        # queries and the primary-demotion update below hit the same DB as the
        # write itself (e.g. the "scrub" alias during backport_data_backup).
        db = using or self._state.db or DEFAULT_DB_ALIAS
        self.normalized_value = self.normalize_value(self.method_type, self.value)
        if not self.normalized_value:
            raise ValueError("contact method requires a value")
        if self.method_type == self.MethodType.PHONE:
            try:
                type(self).check_phone_assignment(
                    self.normalized_value,
                    client_id=self.client_id,
                    contact=self.contact,
                    instance=self,
                    using=db,
                )
            except PhoneAssignmentConflictError as exc:
                if exc.conflict is None:
                    raise ValidationError(
                        "internal phone endpoint cannot be saved as a "
                        "client contact method"
                    ) from exc
                raise ValidationError(
                    "phone number already belongs to "
                    f"{exc.conflict.owner_display_name()}"
                ) from exc

        if self.is_primary:
            queryset = (
                ClientContactMethod.objects.using(db)
                .filter(
                    method_type=self.method_type,
                    is_primary=True,
                )
                .exclude(id=self.id)
            )
            if self.contact_id:
                queryset = queryset.filter(contact_id=self.contact_id)
            else:
                queryset = queryset.filter(
                    client_id=self.client_id, contact__isnull=True
                )
            queryset.update(is_primary=False)

        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    @classmethod
    def normalize_value(cls, method_type: str, value: str | None) -> str:
        if method_type == cls.MethodType.PHONE:
            return cls.normalize_phone(value)
        if method_type == cls.MethodType.EMAIL:
            return (value or "").strip().lower()
        raise ValueError(f"unknown contact method type: {method_type}")

    @staticmethod
    def normalize_phone(value: str | None) -> str:
        digits = re.sub(r"\D+", "", str(value or ""))
        if not digits:
            return ""
        if digits.startswith("64"):
            return f"+{digits}"
        if digits.startswith("0") and len(digits) > 1:
            return f"+64{digits[1:]}"
        return f"+{digits}"

    def owner_client_id(self) -> uuid.UUID | None:
        """The effective client that owns this method (directly or via its contact)."""
        if self.client_id:
            return self.client_id
        if self.contact is not None:
            return self.contact.client_id
        return None

    @classmethod
    def conflicting_client(
        cls,
        normalized_value: str,
        effective_client_id: uuid.UUID | None,
        exclude_id: uuid.UUID | None = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> "ClientContactMethod | None":
        """A phone method for this number owned by a *different* effective client.

        The single source of truth for the "one number, one client" rule, shared by
        the save() guard, the serializer, assign_phone_number, and the Data Quality
        report. Phones only; emails are unaffected.
        """
        queryset = (
            cls.objects.using(using)
            .select_related("client", "contact")
            .filter(
                method_type=cls.MethodType.PHONE,
                normalized_value=normalized_value,
            )
        )
        if exclude_id is not None:
            queryset = queryset.exclude(id=exclude_id)
        return next(
            (
                other
                for other in queryset
                if other.owner_client_id() != effective_client_id
            ),
            None,
        )

    @classmethod
    def check_phone_assignment(
        cls,
        normalized_value: str,
        *,
        client_id: uuid.UUID | None,
        contact: "ClientContact | None",
        instance: "ClientContactMethod | None" = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Enforce the one-number-one-client rule for a proposed phone owner.

        Shared by :meth:`save` and the API serializer so both surfaces apply
        identical semantics:

        - Grandfathering: when ``instance`` is an existing row whose stored
          number and owner match the proposal, no check runs, so legacy
          cross-client numbers can be re-saved (label/primary edits, re-sync)
          without raising.
        - An active internal :class:`~apps.crm.models.PhoneEndpoint` can never
          be a client number.
        - A number owned by a different effective client is rejected.

        Raises:
            PhoneAssignmentConflictError: carrying the conflicting method, or
                ``conflict=None`` for an internal-endpoint collision.
        """
        contact_id = contact.pk if contact is not None else None
        if instance is not None and not instance._state.adding:
            stored = (
                cls.objects.using(using)
                .filter(pk=instance.pk)
                .values("normalized_value", "client_id", "contact_id")
                .first()
            )
            if (
                stored is not None
                and stored["normalized_value"] == normalized_value
                and stored["client_id"] == client_id
                and stored["contact_id"] == contact_id
            ):
                return  # unchanged association -> grandfathered

        from apps.crm.models import PhoneEndpoint

        if (
            PhoneEndpoint.objects.using(using)
            .filter(normalized_number=normalized_value, is_active=True)
            .exists()
        ):
            raise PhoneAssignmentConflictError(None)

        if client_id is not None:
            effective_client_id = client_id
        elif contact is not None:
            effective_client_id = contact.client_id
        else:
            effective_client_id = None
        conflict = cls.conflicting_client(
            normalized_value,
            effective_client_id,
            exclude_id=instance.pk if instance is not None else None,
            using=using,
        )
        if conflict is not None:
            raise PhoneAssignmentConflictError(conflict)

    def owner_display_name(self) -> str:
        if self.contact:
            return f"contact {self.contact.name} at {self.contact.client.name}"
        if self.client:
            return f"client {self.client.name}"
        return "another CRM owner"


class Supplier(Client):
    """
    A Supplier is simply a Client with additional semantics.
    """

    class Meta:
        proxy = True
        db_table = "client_client"


class SupplierSearchAlias(models.Model):
    """Editable search alias attached to a client/supplier contact."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="supplier_search_aliases",
    )
    alias = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["alias"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "alias"],
                name="unique_supplier_search_alias_per_client",
            ),
        ]

    def __str__(self):
        return f"{self.alias} ({self.client.name})"


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
