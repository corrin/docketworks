from rest_framework import serializers

from apps.client.models import Client, ClientContact, SupplierPickupAddress


class ClientContactSerializer(serializers.ModelSerializer):
    """Serializer for ClientContact model."""

    class Meta:
        model = ClientContact
        fields = ClientContact.CLIENTCONTACT_API_FIELDS
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def to_internal_value(self, data):
        """Convert empty strings to None for nullable fields before validation."""
        # Fields that should be NULL instead of empty string
        nullable_fields = ["email", "phone", "position", "notes"]

        for field in nullable_fields:
            if field in data and data[field] == "":
                data[field] = None

        return super().to_internal_value(data)


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

    def to_internal_value(self, data):
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


class ClientSerializer(serializers.ModelSerializer):
    contacts = ClientContactSerializer(many=True, read_only=True)

    class Meta:
        model = Client
        fields = (
            ["id"]
            + Client.CLIENT_DIRECT_FIELDS
            + [
                # Excluded from CLIENT_DIRECT_FIELDS:
                "raw_json",  # debugging blob, not business data
                "django_created_at",  # auto timestamp
                "django_updated_at",  # auto timestamp
                "merged_into",  # ForeignKey relation
                "contacts",  # reverse relation
            ]
        )


class ClientNameOnlySerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ["id", "name"]
        read_only_fields = ["id", "name"]


class StandardErrorSerializer(serializers.Serializer):
    """Standard serialiser for error responses"""

    error = serializers.CharField()
    details = serializers.JSONField(required=False)


class ClientListResponseSerializer(serializers.Serializer):
    """Serializer for client list response"""

    id = serializers.CharField()
    name = serializers.CharField()


class ClientSearchResultSerializer(serializers.Serializer):
    """Serializer for individual client search result"""

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


class ClientSearchResponseSerializer(serializers.Serializer):
    """Serializer for paginated client search response"""

    results = ClientSearchResultSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class ClientCreateSerializer(serializers.Serializer):
    """Serializer for client creation request"""

    name = serializers.CharField(max_length=255)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True
    )
    address = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_account_customer = serializers.BooleanField(default=True)
    allow_jobs = serializers.BooleanField(default=True)


class ClientCreateResponseSerializer(serializers.Serializer):
    """Serializer for client creation response"""

    success = serializers.BooleanField()
    client = ClientSearchResultSerializer()
    message = serializers.CharField()


class ClientErrorResponseSerializer(serializers.Serializer):
    """Serializer for client error responses"""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    details = serializers.CharField(required=False)


class ClientDuplicateErrorResponseSerializer(serializers.Serializer):
    """Serializer for client duplicate error response"""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    existing_client = serializers.DictField()


class ClientDetailResponseSerializer(serializers.Serializer):
    """Serializer for client detail response"""

    id = serializers.CharField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    is_account_customer = serializers.BooleanField()
    is_supplier = serializers.BooleanField()
    allow_jobs = serializers.BooleanField()
    xero_contact_id = serializers.CharField(allow_blank=True)
    xero_tenant_id = serializers.CharField(allow_blank=True)
    primary_contact_name = serializers.CharField(allow_blank=True)
    primary_contact_email = serializers.CharField(allow_blank=True)
    additional_contact_persons = serializers.ListField(required=False)
    all_phones = serializers.ListField(required=False)
    xero_last_modified = serializers.DateTimeField(allow_null=True)
    xero_last_synced = serializers.DateTimeField(allow_null=True)
    xero_archived = serializers.BooleanField()
    xero_merged_into_id = serializers.CharField(allow_blank=True)
    merged_into = serializers.CharField(allow_null=True)
    django_created_at = serializers.DateTimeField()
    django_updated_at = serializers.DateTimeField()
    last_invoice_date = serializers.DateTimeField(allow_null=True)
    total_spend = serializers.CharField()


class ClientUpdateSerializer(serializers.Serializer):
    """Serializer for client update request"""

    name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    is_account_customer = serializers.BooleanField(required=False)
    allow_jobs = serializers.BooleanField(required=False)


class ClientUpdateResponseSerializer(serializers.Serializer):
    """Serializer for client update response"""

    success = serializers.BooleanField()
    client = ClientDetailResponseSerializer()
    message = serializers.CharField()


class JobContactResponseSerializer(serializers.Serializer):
    """Serializer for job contact information response"""

    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.CharField(allow_blank=True, allow_null=True)
    phone = serializers.CharField(allow_blank=True, allow_null=True)
    position = serializers.CharField(allow_blank=True, allow_null=True)
    is_primary = serializers.BooleanField()
    notes = serializers.CharField(allow_blank=True, allow_null=True)


class JobContactUpdateSerializer(JobContactResponseSerializer):
    """Serializer for job contact update request"""


class ClientJobHeaderSerializer(serializers.Serializer):
    """Serializer for job header in client jobs list."""

    job_id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client = serializers.DictField(allow_null=True)
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


class ClientJobsResponseSerializer(serializers.Serializer):
    """Serializer for client jobs list response"""

    results = ClientJobHeaderSerializer(many=True)
