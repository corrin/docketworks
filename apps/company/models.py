import logging
import re
import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Final, Literal

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.core.exceptions import ValidationError
from django.db import DEFAULT_DB_ALIAS, models
from django.db.models.base import ModelBase
from django.db.models.functions import Coalesce
from django.utils import timezone
from xero_python.accounting.models import Address, Contact, Phone

logger = logging.getLogger(__name__)


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


class CompanyQuerySet(models.QuerySet):
    """Custom queryset for Company with precomputed invoice aggregates."""

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


class Company(models.Model):
    # CHECKLIST - when adding a new field or property to Company, check these locations:
    #   1. COMPANY_DIRECT_FIELDS below (if it's a model field)
    #   2. _format_company_detail() in apps/company/services/company_rest_service.py
    #   3. _format_company_summary() in apps/company/services/company_rest_service.py (subset for lists)
    #   4. get_company_for_xero() in this file (Xero API format)
    #   5. update_company_from_raw_json() in apps/workflow/api/xero/reprocess_xero.py (Xero-sourced fields only)
    #   6. _update_company_in_xero() in apps/company/services/company_rest_service.py (Xero API format)
    #   7. CompanyDetailResponseSerializer in apps/company/serializers.py
    #   8. CompanySearchResultSerializer in apps/company/serializers.py (subset for lists)

    objects = CompanyQuerySet.as_manager()

    # Direct scalar model fields (not related objects, not properties).
    COMPANY_DIRECT_FIELDS = [
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
    )  # Indicates if this company is also a supplier
    allow_jobs = models.BooleanField(
        default=True,
        help_text=(
            "If False, this company cannot be selected as the company on a Job. "
            "Use for Xero contacts that must exist (tax authorities, internal "
            "accounts, etc.) but should never appear on a job. Automatically "
            "set to False when a company is archived or merged in Xero."
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

    # Fields to track merged companies in Xero
    xero_archived = models.BooleanField(
        default=False,
        help_text="Indicates if this company has been archived/merged in Xero",
    )
    xero_merged_into_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="The Xero contact ID this company was merged into (temporary storage)",
    )
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_from_companies",
        help_text="The company this was merged into",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            GinIndex(
                SearchVector("name", config="english"),
                name="company_name_fts_idx",
            ),
            GinIndex(
                fields=["name"],
                name="company_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self):
        return self.name

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        update_fields = _augment_update_fields(update_fields, "django_updated_at")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def validate_for_xero(self) -> bool:
        """
        Validate if the company data is sufficient to sync to Xero.
        Only name is required by Xero.
        """
        if not self.name:
            logger.error(f"Company {self.id} does not have a valid name.")
            return False
        return True

    @property
    def last_invoice_date(self):
        if "_last_invoice_date" not in self.__dict__:
            raise RuntimeError(
                "Company.last_invoice_date requires "
                "Company.objects.with_invoice_summary()."
            )
        return self.__dict__["_last_invoice_date"]

    @last_invoice_date.setter
    def last_invoice_date(self, value):
        self.__dict__["_last_invoice_date"] = value

    @property
    def total_spend(self):
        if "_total_spend" not in self.__dict__:
            raise RuntimeError(
                "Company.total_spend requires Company.objects.with_invoice_summary()."
            )
        return self.__dict__["_total_spend"]

    @total_spend.setter
    def total_spend(self, value):
        self.__dict__["_total_spend"] = value

    def get_company_for_xero(self):
        """
        Build a xero_python.accounting.models.Contact for syncing to Xero.

        Returns an SDK model instance (not a dict) so the SDK's attribute_map
        translates Python snake_case to Xero's PascalCase wire format. Raw
        dicts ship verbatim and Xero silently drops every non-Name field.
        """
        if not self.name:
            raise ValueError(
                f"Company {self.id} is missing a name, which is required for Xero."
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
        """The company's own primary phone number, or "" when it has none.

        Single-object flows only (Xero sync, PO PDFs). Queryset consumers must
        use ClientContactMethod.primary_phone_annotation instead.
        """
        method = (
            self.contact_methods.filter(
                method_type=ClientContactMethod.MethodType.PHONE
            )
            .order_by(*PRIMARY_PHONE_ORDERING)
            .first()
        )
        return method.value if method else ""

    def get_final_company(self) -> "Company":
        """
        Follow the merge chain to get the final company.
        If this company was merged into another, return that company
        (following the chain).
        Otherwise return self.
        """
        current = self
        seen = {self.id}  # Prevent infinite loops

        while current.merged_into:
            if current.merged_into.id in seen:
                logger.warning(f"Circular merge chain detected for company {self.id}")
                break
            seen.add(current.merged_into.id)
            current = current.merged_into

        return current


class Person(models.Model):
    """A human independent of any single company relationship."""

    PERSON_API_FIELDS = [
        "id",
        "name",
        "email",
        "is_active",
        "created_at",
        "updated_at",
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, db_index=True)
    email = models.EmailField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        update_fields = _augment_update_fields(update_fields, "updated_at")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class CompanyPersonLink(models.Model):
    """
    Represents a contact person for a company.
    This model stores contact information that was previously synced with Xero
    but is now managed entirely within our application.
    """

    # CHECKLIST - when adding a new field or property to ClientContact, check these locations:
    #   1. CLIENTCONTACT_API_FIELDS or CLIENTCONTACT_INTERNAL_FIELDS below (if it's a model field)
    #   2. ClientContactSerializer in apps/company/serializers.py (uses CLIENTCONTACT_API_FIELDS)
    #   3. ClientContactSerializer.to_internal_value() nullable_fields list (converts "" → None)
    #   4. JobContactResponseSerializer in apps/company/serializers.py (subset for job context)
    #   5. ClientContactViewSet in apps/company/views/contact_viewset.py (CRUD operations)
    #   6. Job.contact FK in apps/job/models/job.py (relationship to ClientContact)
    #   7. reprocess_xero.py in apps/workflow/api/xero/ (Xero sync creates contacts)
    #
    # Database fields exposed via API serializers
    CLIENTCONTACT_API_FIELDS = [
        "id",
        "company",
        "person",
        "name",
        "email",
        "xero_name",
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
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="contacts",
        help_text="The company this contact belongs to",
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="company_links",
    )
    name = models.CharField(max_length=255, help_text="Full name of the contact person")
    email = models.EmailField(
        null=True, blank=True, help_text="Email address of the contact"
    )
    xero_name = models.CharField(max_length=255, null=True, blank=True)
    position = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Job title if it's helpful - else leave blank",
    )
    is_primary = models.BooleanField(
        default=False,
        help_text="Indicates if this is the primary contact for the company",
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
        verbose_name = "Company Person Link"
        verbose_name_plural = "Company Person Links"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="unique_company_contact_name",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.company.name})"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        update_fields = _augment_update_fields(update_fields, "updated_at")
        if self.person_id is None:
            self.person = Person.objects.create(
                name=self.name,
                email=self.email,
                is_active=self.is_active,
            )
            update_fields = _augment_update_fields(update_fields, "person")
        if self.xero_name is None:
            self.xero_name = self.name
            update_fields = _augment_update_fields(update_fields, "xero_name")

        # If this contact is being set as primary, ensure no other contacts
        # for this company are marked as primary
        if self.is_primary:
            CompanyPersonLink.objects.filter(
                company=self.company, is_primary=True
            ).exclude(id=self.id).update(is_primary=False)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class PhoneAssignmentConflictError(Exception):
    """A phone number cannot be assigned to the proposed company/contact owner.

    ``conflict`` is the existing :class:`ClientContactMethod` owned by a
    different effective company, or ``None`` when the number is an active
    internal :class:`~apps.crm.models.PhoneEndpoint`.
    """

    def __init__(self, conflict: "ClientContactMethod | None") -> None:
        self.conflict = conflict
        if conflict is None:
            message = "phone number is an active internal phone endpoint"
        else:
            message = f"phone number already belongs to {conflict.owner_display_name()}"
        super().__init__(message)


# The primary-phone ordering rule: primary first, then label/value as a
# stable tie-break. Single source — every primary-phone consumer must use it.
PRIMARY_PHONE_ORDERING: Final[tuple[str, str, str]] = ("-is_primary", "label", "value")

PhoneOwner = Literal["company", "contact", "person"]


class ContactMethod(models.Model):
    """Phone or email address owned by a company or one of its contacts."""

    class MethodType(models.TextChoices):
        PHONE = "phone", "Phone"
        EMAIL = "email", "Email"

    class Source(models.TextChoices):
        IMPORTED = "imported", "Imported"
        LOCAL = "local", "Local"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="contact_methods",
    )
    contact = models.ForeignKey(
        CompanyPersonLink,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="contact_methods",
    )
    person = models.ForeignKey(
        Person,
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
        verbose_name = "Contact Method"
        verbose_name_plural = "Contact Methods"
        constraints: list[models.BaseConstraint] = []

    def __str__(self) -> str:
        owner = self.person or self.contact or self.company
        return f"{self.method_type}: {self.value} ({owner})"

    @classmethod
    def primary_phone_annotation(cls, *, owner: PhoneOwner, outer_ref: str) -> Coalesce:
        """Queryset annotation: the owner's primary phone value, "" when it has none.

        ``outer_ref`` names the outer queryset's column holding the owner's id
        (e.g. "pk" on a Company queryset, "company_id" on a Job queryset).
        """
        candidates = (
            cls.objects.filter(
                method_type=cls.MethodType.PHONE, **{owner: models.OuterRef(outer_ref)}
            )
            .order_by(*PRIMARY_PHONE_ORDERING)
            .values("value")[:1]
        )
        return Coalesce(
            models.Subquery(candidates),
            models.Value(""),
            output_field=models.CharField(),
        )

    @classmethod
    def primary_phone_for_link_annotation(cls) -> Coalesce:
        """Primary phone for a company-person link during contact→person migration."""
        candidates = (
            cls.objects.filter(method_type=cls.MethodType.PHONE)
            .filter(
                models.Q(person=models.OuterRef("person_id"))
                | models.Q(contact=models.OuterRef("pk"))
            )
            .order_by(*PRIMARY_PHONE_ORDERING)
            .values("value")[:1]
        )
        return Coalesce(
            models.Subquery(candidates),
            models.Value(""),
            output_field=models.CharField(),
        )

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
        update_fields = _augment_update_fields(update_fields, "normalized_value")
        if not self.normalized_value:
            raise ValueError("contact method requires a value")
        if self.method_type == self.MethodType.PHONE:
            try:
                type(self).check_phone_assignment(
                    self.normalized_value,
                    company_id=self.company_id,
                    contact=self.contact,
                    person=self.person,
                    instance=self,
                    using=db,
                )
            except PhoneAssignmentConflictError as exc:
                if exc.conflict is None:
                    raise ValidationError(
                        "internal phone endpoint cannot be saved as a "
                        "company contact method"
                    ) from exc
                raise ValidationError(
                    "phone number already belongs to "
                    f"{exc.conflict.owner_display_name()}"
                ) from exc

        if self.is_primary:
            queryset = (
                ContactMethod.objects.using(db)
                .filter(
                    method_type=self.method_type,
                    is_primary=True,
                )
                .exclude(id=self.id)
            )
            if self.person_id:
                queryset = queryset.filter(person_id=self.person_id)
            elif self.contact_id:
                queryset = queryset.filter(contact_id=self.contact_id)
            else:
                queryset = queryset.filter(
                    company_id=self.company_id, contact__isnull=True
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

    def owner_company_id(self) -> uuid.UUID | None:
        """The effective company that owns this method (directly or via its contact)."""
        company_ids = self.owner_company_ids()
        if len(company_ids) == 1:
            return next(iter(company_ids))
        if company_ids:
            return sorted(company_ids)[0]
        return None

    def owner_company_ids(self) -> set[uuid.UUID]:
        """Companies this method can be traced to through its owner."""
        if self.company_id:
            return {self.company_id}
        if self.person is not None:
            return set(self.person.company_links.values_list("company_id", flat=True))
        if self.contact is not None:
            return {self.contact.company_id}
        return set()

    @classmethod
    def conflicting_company(
        cls,
        normalized_value: str,
        effective_company_ids: set[uuid.UUID],
        exclude_id: uuid.UUID | None = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> "ContactMethod | None":
        """A phone method for this number owned by a *different* effective company.

        The single source of truth for the "one number, one company" rule, shared by
        the save() guard, the serializer, assign_phone_number, and the Data Quality
        report. Phones only; emails are unaffected.
        """
        queryset = (
            cls.objects.using(using)
            .select_related("company", "contact")
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
                if not other.owner_company_ids().intersection(effective_company_ids)
            ),
            None,
        )

    @classmethod
    def check_phone_assignment(
        cls,
        normalized_value: str,
        *,
        company_id: uuid.UUID | None,
        contact: "CompanyPersonLink | None",
        person: "Person | None" = None,
        instance: "ContactMethod | None" = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Enforce the one-number-one-company rule for a proposed phone owner.

        Shared by :meth:`save` and the API serializer so both surfaces apply
        identical semantics:

        - Grandfathering: when ``instance`` is an existing row whose stored
          number and owner match the proposal, no check runs, so legacy
          cross-company numbers can be re-saved (label/primary edits, re-sync)
          without raising.
        - An active internal :class:`~apps.crm.models.PhoneEndpoint` can never
          be a company number.
        - A number owned by a different effective company is rejected.

        Raises:
            PhoneAssignmentConflictError: carrying the conflicting method, or
                ``conflict=None`` for an internal-endpoint collision.
        """
        contact_id = contact.pk if contact is not None else None
        person_id = person.pk if person is not None else None
        if instance is not None and not instance._state.adding:
            stored = (
                cls.objects.using(using)
                .filter(pk=instance.pk)
                .values("normalized_value", "company_id", "contact_id", "person_id")
                .first()
            )
            if (
                stored is not None
                and stored["normalized_value"] == normalized_value
                and stored["company_id"] == company_id
                and stored["contact_id"] == contact_id
                and stored["person_id"] == person_id
            ):
                return  # unchanged association -> grandfathered

        from apps.crm.models import PhoneEndpoint

        if (
            PhoneEndpoint.objects.using(using)
            .filter(normalized_number=normalized_value, is_active=True)
            .exists()
        ):
            raise PhoneAssignmentConflictError(None)

        if company_id is not None:
            effective_company_ids = {company_id}
        elif contact is not None:
            effective_company_ids = {contact.company_id}
        elif person is not None:
            effective_company_ids = set(
                person.company_links.using(using).values_list("company_id", flat=True)
            )
        else:
            effective_company_ids = set()
        conflict = cls.conflicting_company(
            normalized_value,
            effective_company_ids,
            exclude_id=instance.pk if instance is not None else None,
            using=using,
        )
        if conflict is not None:
            raise PhoneAssignmentConflictError(conflict)

    def owner_display_name(self) -> str:
        if self.contact:
            return f"contact {self.contact.name} at {self.contact.company.name}"
        if self.person:
            return f"person {self.person.name}"
        if self.company:
            return f"company {self.company.name}"
        return "another CRM owner"


# Temporary import aliases while consumers are moved to person naming.
ClientContact = CompanyPersonLink
ClientContactMethod = ContactMethod


class Supplier(Company):
    """
    A Supplier is simply a Company with additional semantics.
    """

    class Meta:
        proxy = True


class SupplierSearchAlias(models.Model):
    """Editable search alias attached to a company/supplier contact."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
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
                fields=["company", "alias"],
                name="unique_supplier_search_alias_per_company",
            ),
        ]

    def __str__(self):
        return f"{self.alias} ({self.company.name})"


class SupplierPickupAddress(models.Model):
    """
    Represents a pickup/delivery address for a supplier or company.

    Despite the name, this model can be used for any Company - not just those
    marked as suppliers. Suppliers can have multiple pickup addresses, with
    one marked as primary. Useful for tracking warehouse locations, branch
    offices, or delivery points.
    """

    # CHECKLIST - when adding a new field or property to SupplierPickupAddress, check:
    #   1. SUPPLIERPICKUPADDRESS_API_FIELDS below (if it's a model field)
    #   2. SupplierPickupAddressSerializer in apps/company/serializers.py
    #   3. SupplierPickupAddressSerializer.to_internal_value() nullable_fields list
    #   4. SupplierPickupAddressViewSet in apps/company/views/supplier_pickup_address_viewset.py
    #   5. PurchaseOrder.pickup_address FK in apps/purchasing/models.py
    #   6. PurchaseOrderDetailSerializer in apps/purchasing/serializers.py
    #   7. PurchaseOrderPDFGenerator in apps/purchasing/services/purchase_order_pdf_service.py
    #
    # Database fields exposed via API serializers
    SUPPLIERPICKUPADDRESS_API_FIELDS = [
        "id",
        "company",
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
    company = models.ForeignKey(
        Company,
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
                fields=["company", "name"],
                name="unique_supplier_pickup_address_name",
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.city} ({self.company.name})"

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
        # for this company are marked as primary
        if self.is_primary:
            SupplierPickupAddress.objects.filter(
                company=self.company, is_primary=True
            ).exclude(id=self.id).update(is_primary=False)
        super().save(*args, **kwargs)
