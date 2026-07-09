from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.company.models import (
    Company,
    CompanyPersonLink,
    ContactMethod,
    Person,
    PhoneAssignmentConflictError,
    SupplierPickupAddress,
    SupplierSearchAlias,
)


def set_primary_phone(owner: Company | Person, raw_value: str) -> None:
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
    else:
        owner_field = "person"
    phone_methods = ContactMethod.objects.filter(
        method_type=ContactMethod.MethodType.PHONE, **{owner_field: owner}
    )
    old_primary = phone_methods.filter(is_primary=True).first()
    old_number = old_primary.normalized_value if old_primary else ""
    normalized_value = ContactMethod.normalize_phone(value)
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
        method = ContactMethod.objects.create(
            method_type=ContactMethod.MethodType.PHONE,
            value=value,
            is_primary=True,
            **{owner_field: owner},
        )

    numbers = sorted(
        number for number in {old_number, method.normalized_value} if number
    )
    transaction.on_commit(lambda: rematch_phone_calls_task.delay(numbers))


class CompanyPersonLinkSerializer(serializers.ModelSerializer):
    """Serializer for a person's relationship to a company."""

    person = serializers.UUIDField(source="person_id", read_only=True)
    person_name = serializers.CharField(source="person.name")
    person_email = serializers.EmailField(
        source="person.email", required=False, allow_blank=True, allow_null=True
    )
    # Backed by ContactMethod: reads come from the viewset's
    # primary_phone_annotation; writes upsert the contact's primary method.
    phone = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=""
    )

    class Meta:
        model = CompanyPersonLink
        fields = [
            "id",
            "company",
            "person",
            "person_name",
            "person_email",
            "xero_name",
            "position",
            "is_primary",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
            "phone",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def to_internal_value(self, data: Any) -> Any:
        """Convert empty strings to None for nullable fields before validation."""
        # Fields that should be NULL instead of empty string
        nullable_fields = ["person_email", "position", "notes"]

        for field in nullable_fields:
            if field in data and data[field] == "":
                data[field] = None

        return super().to_internal_value(data)

    def create(self, validated_data):
        raw_phone = validated_data.pop("phone", None)  # not a model field
        person_value = validated_data.pop("person", None)
        with transaction.atomic():
            if isinstance(person_value, dict):
                person = Person.objects.create(
                    name=person_value["name"],
                    email=person_value.get("email"),
                    is_active=validated_data.get("is_active", True),
                )
                validated_data["person"] = person
            else:
                raise serializers.ValidationError(
                    {"person_name": "This field is required."}
                )
            if validated_data.get("xero_name") is None:
                validated_data["xero_name"] = person.name
            link = super().create(validated_data)
            return self._apply_phone(link, raw_phone)

    def update(self, instance, validated_data):
        raw_phone = validated_data.pop("phone", None)  # not a model field
        person_data = validated_data.pop("person", None)
        with transaction.atomic():
            link = super().update(instance, validated_data)
            if isinstance(person_data, dict):
                person_update_fields = ["updated_at"]
                if "name" in person_data:
                    link.person.name = person_data["name"]
                    person_update_fields.append("name")
                if "email" in person_data:
                    link.person.email = person_data["email"]
                    person_update_fields.append("email")
                link.person.save(update_fields=person_update_fields)
            return self._apply_phone(link, raw_phone)

    def _apply_phone(
        self, link: CompanyPersonLink, raw_phone: str | None
    ) -> CompanyPersonLink:
        """Upsert the primary phone; blank/omitted input is a no-op (deleting
        numbers is PhoneNumberManager's job, not this form's)."""
        if raw_phone and raw_phone.strip():
            try:
                set_primary_phone(link.person, raw_phone)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"phone": exc.messages}) from exc
        else:
            pass  # blank phone: leave existing contact methods untouched
        # The phone field always reads from a queryset annotation; give the
        # write response the same shape by re-fetching through it.
        return CompanyPersonLink.objects.annotate(
            phone=ContactMethod.primary_phone_for_link_annotation()
        ).get(pk=link.pk)


class ContactMethodSerializer(serializers.ModelSerializer):
    """Serializer for canonical company/person phone and email methods."""

    owner_company = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    person_name = serializers.SerializerMethodField()

    class Meta:
        model = ContactMethod
        fields = [
            "id",
            "company",
            "owner_company",
            "company_name",
            "person",
            "person_name",
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
            "person_name",
            "normalized_value",
            "created_at",
            "updated_at",
        ]

    def get_owner_company(self, obj: ContactMethod) -> str:
        if obj.company_id:
            return str(obj.company_id)
        if obj.person_id:
            company_id = obj.owner_company_id()
            return str(company_id) if company_id else ""
        return ""

    def get_company_name(self, obj: ContactMethod) -> str:
        if obj.company:
            return obj.company.name
        if obj.person_id:
            person = obj.person
            if person is None:
                raise RuntimeError(f"Contact method {obj.id} has no person")
            link = (
                person.company_links.select_related("company")
                .order_by("-is_primary", "company__name")
                .first()
            )
            return link.company.name if link else ""
        return ""

    def get_person_name(self, obj: ContactMethod) -> str:
        return obj.person.name if obj.person else ""

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        company = attrs.get("company", getattr(self.instance, "company", None))
        person = attrs.get("person", getattr(self.instance, "person", None))
        owner_count = sum(1 for owner in (company, person) if owner)
        if owner_count != 1:
            raise serializers.ValidationError(
                "Exactly one of company or person is required"
            )
        method_type = attrs.get(
            "method_type", getattr(self.instance, "method_type", None)
        )
        value = attrs.get("value", getattr(self.instance, "value", None))
        if method_type == ContactMethod.MethodType.PHONE:
            normalized = ContactMethod.normalize_phone(value)
            try:
                ContactMethod.check_phone_assignment(
                    normalized,
                    company_id=company.id if company else None,
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
    contacts = CompanyPersonLinkSerializer(many=True, read_only=True)

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
    # Stored as the client's primary ContactMethod, not a Client column
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
    # Stored as the client's primary ContactMethod, not a Client column
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    address = serializers.CharField(required=False, allow_blank=True)
    is_account_customer = serializers.BooleanField(required=False)
    allow_jobs = serializers.BooleanField(required=False)


class CompanyUpdateResponseSerializer(serializers.Serializer):
    """Serializer for company update response"""

    success = serializers.BooleanField()
    company = CompanyDetailResponseSerializer()
    message = serializers.CharField()


class JobPersonBaseSerializer(serializers.Serializer):
    """Fields shared by the job person response and update serializers."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True, allow_null=True)


class JobPersonResponseSerializer(JobPersonBaseSerializer):
    """Serializer for job person information response"""


class JobPersonUpdateSerializer(JobPersonBaseSerializer):
    """Serializer for job person update request"""


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
