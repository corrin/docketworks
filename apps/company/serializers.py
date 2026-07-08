from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.company.models import (
    ClientContact,
    ClientContactMethod,
    Company,
    Person,
    PhoneAssignmentConflictError,
    SupplierPickupAddress,
    SupplierSearchAlias,
)


def set_primary_phone(owner: Company | ClientContact | Person, raw_value: str) -> None:
    """Point the owner's primary phone at ``raw_value`` (non-blank).

    Reuses an existing method carrying the same normalized number (promoting
    it) or the current primary (renumbering it) before creating a new row, so
    the per-owner uniqueness and single-primary constraints hold. Ownership
    conflicts raise the model's ValidationError for the caller to surface.
    """
    # Lazy: apps.job.models imports this module; a module-level crm.tasks
    # import closes an import cycle that breaks mypy's cross-module inference.
    from apps.crm.tasks import rematch_phone_calls_task

    value = raw_value.strip()
    if isinstance(owner, Company):
        owner_field = "company"
    elif isinstance(owner, Person):
        owner_field = "person"
    else:
        owner_field = "contact"
    phone_methods = ClientContactMethod.objects.filter(
        method_type=ClientContactMethod.MethodType.PHONE, **{owner_field: owner}
    )
    old_primary = phone_methods.filter(is_primary=True).first()
    old_number = old_primary.normalized_value if old_primary else ""
    normalized_value = ClientContactMethod.normalize_phone(value)
    if not normalized_value:
        raise DjangoValidationError("Phone number must contain at least one digit")

    same_number = phone_methods.filter(normalized_value=normalized_value).first()

    if same_number is not None:
        same_number.value = value
        same_number.is_primary = True  # save() demotes any other primary
        same_number.save()
        method = same_number
    elif old_primary is not None:
        old_primary.value = value
        old_primary.save()
        method = old_primary
    else:
        create_kwargs = {owner_field: owner}
        if isinstance(owner, ClientContact) and owner.person_id:
            create_kwargs["person"] = owner.person
        method = ClientContactMethod.objects.create(
            method_type=ClientContactMethod.MethodType.PHONE,
            value=value,
            is_primary=True,
            **create_kwargs,
        )

    numbers = sorted(
        number for number in {old_number, method.normalized_value} if number
    )
    transaction.on_commit(lambda: rematch_phone_calls_task.delay(numbers))


class ClientContactSerializer(serializers.ModelSerializer):
    """Serializer for ClientContact model."""

    # Backed by ClientContactMethod: reads come from the viewset's
    # primary_phone_annotation; writes upsert the contact's primary method.
    phone = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=""
    )

    class Meta:
        model = ClientContact
        fields = ClientContact.CLIENTCONTACT_API_FIELDS + ["phone"]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def to_internal_value(self, data: Any) -> Any:
        """Convert empty strings to None for nullable fields before validation."""
        # Fields that should be NULL instead of empty string
        nullable_fields = ["email", "position", "notes"]

        for field in nullable_fields:
            if field in data and data[field] == "":
                data[field] = None

        return super().to_internal_value(data)

    def create(self, validated_data):
        raw_phone = validated_data.pop("phone", None)  # not a model field
        with transaction.atomic():
            person = Person.objects.create(
                name=validated_data["name"],
                email=validated_data.get("email"),
                is_active=validated_data.get("is_active", True),
            )
            validated_data["person"] = person
            validated_data["xero_name"] = validated_data["name"]
            contact = super().create(validated_data)
            return self._apply_phone(contact, raw_phone)

    def update(self, instance, validated_data):
        raw_phone = validated_data.pop("phone", None)  # not a model field
        with transaction.atomic():
            contact = super().update(instance, validated_data)
            if contact.person_id:
                person_update_fields = ["updated_at"]
                if "name" in validated_data:
                    contact.person.name = contact.name
                    person_update_fields.append("name")
                if "email" in validated_data:
                    contact.person.email = contact.email
                    person_update_fields.append("email")
                if "is_active" in validated_data:
                    contact.person.is_active = contact.is_active
                    person_update_fields.append("is_active")
                contact.person.save(update_fields=person_update_fields)
            return self._apply_phone(contact, raw_phone)

    def _apply_phone(
        self, contact: ClientContact, raw_phone: str | None
    ) -> ClientContact:
        """Upsert the primary phone; blank/omitted input is a no-op (deleting
        numbers is PhoneNumberManager's job, not this form's)."""
        if raw_phone and raw_phone.strip():
            try:
                set_primary_phone(contact, raw_phone)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"phone": exc.messages}) from exc
        else:
            pass  # blank phone: leave existing contact methods untouched
        # The phone field always reads from a queryset annotation; give the
        # write response the same shape by re-fetching through it.
        return ClientContact.objects.annotate(
            phone=ClientContactMethod.primary_phone_for_link_annotation()
        ).get(pk=contact.pk)


class ClientContactMethodSerializer(serializers.ModelSerializer):
    """Serializer for canonical company/contact phone and email methods."""

    owner_company = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    contact_name = serializers.SerializerMethodField()

    class Meta:
        model = ClientContactMethod
        fields = [
            "id",
            "company",
            "owner_company",
            "company_name",
            "contact",
            "contact_name",
            "person",
            "method_type",
            "value",
            "normalized_value",
            "label",
            "is_primary",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "owner_company",
            "company_name",
            "contact_name",
            "normalized_value",
            "created_at",
            "updated_at",
        ]

    def get_owner_company(self, obj: ClientContactMethod) -> str:
        if obj.company_id:
            return str(obj.company_id)
        if obj.person_id:
            company_id = obj.owner_company_id()
            return str(company_id) if company_id else ""
        return str(obj.contact.company_id) if obj.contact else ""

    def get_company_name(self, obj: ClientContactMethod) -> str:
        if obj.company:
            return obj.company.name
        if obj.person_id:
            link = (
                obj.person.company_links.select_related("company")
                .order_by("-is_primary", "company__name")
                .first()
            )
            return link.company.name if link else ""
        return obj.contact.company.name if obj.contact else ""

    def get_contact_name(self, obj: ClientContactMethod) -> str:
        return obj.contact.name if obj.contact else ""

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        company = attrs.get("company", getattr(self.instance, "company", None))
        contact = attrs.get("contact", getattr(self.instance, "contact", None))
        person = attrs.get("person", getattr(self.instance, "person", None))
        owner_count = sum(1 for owner in (company, contact, person) if owner)
        if owner_count != 1:
            raise serializers.ValidationError(
                "Exactly one of company, contact, or person is required"
            )
        method_type = attrs.get(
            "method_type", getattr(self.instance, "method_type", None)
        )
        value = attrs.get("value", getattr(self.instance, "value", None))
        if method_type == ClientContactMethod.MethodType.PHONE:
            normalized = ClientContactMethod.normalize_phone(value)
            try:
                ClientContactMethod.check_phone_assignment(
                    normalized,
                    company_id=company.id if company else None,
                    contact=contact,
                    person=person,
                    instance=self.instance,
                )
            except PhoneAssignmentConflictError as exc:
                if exc.conflict is None:
                    raise serializers.ValidationError(
                        {
                            "value": "Internal phone endpoint cannot be assigned "
                            "to a company."
                        }
                    ) from exc
                raise serializers.ValidationError(
                    {
                        "value": (
                            "Phone number already belongs to "
                            f"{exc.conflict.owner_display_name()}."
                        )
                    }
                ) from exc
        return attrs


class SupplierPickupAddressSerializer(serializers.ModelSerializer):
    """Serializer for SupplierPickupAddress model (delivery/pickup locations)."""

    formatted_address = serializers.CharField(read_only=True)

    class Meta:
        model = SupplierPickupAddress
        fields = SupplierPickupAddress.SUPPLIERPICKUPADDRESS_API_FIELDS + [
            "formatted_address"
        ]
        read_only_fields = [
            "id",
            "is_active",
            "created_at",
            "updated_at",
            "formatted_address",
        ]

    def to_internal_value(self, data: Any) -> Any:
        """Convert empty strings to None for nullable fields before validation."""
        nullable_fields = [
            "suburb",
            "state",
            "postal_code",
            "notes",
            "google_place_id",
            "latitude",
            "longitude",
        ]

        for field in nullable_fields:
            if field in data and data[field] == "":
                data[field] = None

        return super().to_internal_value(data)


class CompanySerializer(serializers.ModelSerializer):
    contacts = ClientContactSerializer(many=True, read_only=True)

    class Meta:
        model = Company
        fields = (
            ["id"]
            + Company.COMPANY_DIRECT_FIELDS
            + [
                # Excluded from COMPANY_DIRECT_FIELDS:
                "raw_json",  # debugging blob, not business data
                "django_created_at",  # auto timestamp
                "django_updated_at",  # auto timestamp
                "merged_into",  # ForeignKey relation
                "contacts",  # reverse relation
            ]
        )


class CompanyNameOnlySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name"]
        read_only_fields = ["id", "name"]


class StandardErrorSerializer(serializers.Serializer):
    """Standard serialiser for error responses"""

    error = serializers.CharField()
    details = serializers.JSONField(required=False)


class CompanyListResponseSerializer(serializers.Serializer):
    """Serializer for company list response"""

    id = serializers.CharField()
    name = serializers.CharField()


class CompanySearchResultSerializer(serializers.Serializer):
    """Serializer for individual company search result"""

    id = serializers.CharField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    is_account_customer = serializers.BooleanField()
    is_supplier = serializers.BooleanField()
    allow_jobs = serializers.BooleanField()
    xero_contact_id = serializers.CharField(allow_blank=True)
    last_invoice_date = serializers.DateTimeField(allow_null=True)
    total_spend = serializers.CharField()


class CompanySearchResponseSerializer(serializers.Serializer):
    """Serializer for paginated company search response"""

    results = CompanySearchResultSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class SupplierSearchAliasSerializer(serializers.ModelSerializer):
    """Supplier search alias attached to a company/contact."""

    class Meta:
        model = SupplierSearchAlias
        fields = ["id", "company", "alias", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "company", "is_active", "created_at", "updated_at"]


class SupplierSearchAliasCreateSerializer(serializers.Serializer):
    """Create supplier search alias request."""

    alias = serializers.CharField(max_length=255, trim_whitespace=True)

    def validate_alias(self, value: str) -> str:
        alias = value.strip()
        if not alias:
            raise serializers.ValidationError("Alias is required")
        return alias


class CompanyCreateSerializer(serializers.Serializer):
    """Serializer for company creation request"""

    name = serializers.CharField(max_length=255)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    # Stored as the client's primary ClientContactMethod, not a Client column
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    address = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_account_customer = serializers.BooleanField(default=True)
    allow_jobs = serializers.BooleanField(default=True)


class CompanyCreateResponseSerializer(serializers.Serializer):
    """Serializer for company creation response"""

    success = serializers.BooleanField()
    company = CompanySearchResultSerializer()
    message = serializers.CharField()


class CompanyErrorResponseSerializer(serializers.Serializer):
    """Serializer for company error responses"""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    details = serializers.CharField(required=False)
    error_id = serializers.CharField(required=False)


class CompanyDuplicateErrorResponseSerializer(serializers.Serializer):
    """Serializer for company duplicate error response"""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    existing_company = serializers.DictField()


class CompanyDetailResponseSerializer(serializers.Serializer):
    """Serializer for company detail response"""

    id = serializers.CharField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    is_account_customer = serializers.BooleanField()
    is_supplier = serializers.BooleanField()
    allow_jobs = serializers.BooleanField()
    xero_contact_id = serializers.CharField(allow_blank=True)
    xero_tenant_id = serializers.CharField(allow_blank=True)
    primary_contact_name = serializers.CharField(allow_blank=True)
    primary_contact_email = serializers.CharField(allow_blank=True)
    additional_contact_persons = serializers.ListField(required=False)
    xero_last_modified = serializers.DateTimeField(allow_null=True)
    xero_last_synced = serializers.DateTimeField(allow_null=True)
    xero_archived = serializers.BooleanField()
    xero_merged_into_id = serializers.CharField(allow_blank=True)
    merged_into = serializers.CharField(allow_null=True)
    django_created_at = serializers.DateTimeField()
    django_updated_at = serializers.DateTimeField()
    last_invoice_date = serializers.DateTimeField(allow_null=True)
    total_spend = serializers.CharField()
    phone = serializers.CharField(allow_blank=True)


class CompanyUpdateSerializer(serializers.Serializer):
    """Serializer for company update request"""

    name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    # Stored as the client's primary ClientContactMethod, not a Client column
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    address = serializers.CharField(required=False, allow_blank=True)
    is_account_customer = serializers.BooleanField(required=False)
    allow_jobs = serializers.BooleanField(required=False)


class CompanyUpdateResponseSerializer(serializers.Serializer):
    """Serializer for company update response"""

    success = serializers.BooleanField()
    company = CompanyDetailResponseSerializer()
    message = serializers.CharField()


class JobContactBaseSerializer(serializers.Serializer):
    """Fields shared by the job contact response and update serializers."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True, allow_null=True)
    position = serializers.CharField(allow_blank=True, allow_null=True)
    is_primary = serializers.BooleanField()
    notes = serializers.CharField(allow_blank=True, allow_null=True)


class JobContactResponseSerializer(JobContactBaseSerializer):
    """Serializer for job contact information response"""


class JobContactUpdateSerializer(JobContactBaseSerializer):
    """Serializer for job contact update request"""


class CompanyJobHeaderSerializer(serializers.Serializer):
    """Serializer for job header in company jobs list."""

    job_id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    company = serializers.DictField(allow_null=True)
    status = serializers.CharField()
    pricing_methodology = serializers.CharField(allow_null=True)
    speed_quality_tradeoff = serializers.CharField()
    fully_invoiced = serializers.BooleanField()
    has_quote_in_xero = serializers.BooleanField()
    is_fixed_price = serializers.BooleanField()
    quote_acceptance_date = serializers.DateTimeField(allow_null=True)
    paid = serializers.BooleanField()
    rejected_flag = serializers.BooleanField()
    min_people = serializers.IntegerField()
    max_people = serializers.IntegerField()


class CompanyJobsResponseSerializer(serializers.Serializer):
    """Serializer for company jobs list response"""

    results = CompanyJobHeaderSerializer(many=True)
