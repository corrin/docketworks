from rest_framework import serializers

# Existing models used in this serializer module
from .models import (
    AIProvider,
    AppError,
    CompanyDefaults,
    XeroAccount,
    XeroError,
    XeroPayItem,
    XeroToken,
)
from .models.settings_metadata import COMPANY_DEFAULTS_READ_ONLY_FIELDS


class XeroTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = XeroToken
        fields = "__all__"


class AIProviderSerializer(serializers.ModelSerializer):
    """
    Serializer for reading AIProvider instances.
    This serializer is read-only and excludes the `api_key` for security.
    """

    class Meta:
        model = AIProvider
        fields = (
            "id",
            "name",
            "provider_type",
            "model_name",
            "default",
        )


class CompanyDefaultsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyDefaults
        fields = "__all__"
        read_only_fields = tuple(COMPANY_DEFAULTS_READ_ONLY_FIELDS)


class XeroAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = XeroAccount
        fields = "__all__"


class XeroPayItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = XeroPayItem
        fields = "__all__"


class AIProviderCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating AIProvider instances.
    This serializer handles the `api_key` securely by making it write-only.
    """

    # Make api_key write-only for security. It can be provided on create/update,
    # but it will never be included in a response.
    api_key = serializers.CharField(
        write_only=True,
        required=False,  # Not required on update, but validated below for create.
        allow_blank=True,
        style={"input_type": "password"},
        help_text="API Key for the provider. Leave blank to keep unchanged on update.",
    )

    class Meta:
        model = AIProvider
        fields = (
            "name",
            "provider_type",
            "model_name",
            "default",
            "api_key",
        )

    def validate(self, data):
        """
        Validate that a new provider has an API key.
        """
        # On create (when instance is not present), api_key is required.
        if not self.instance and not data.get("api_key"):
            raise serializers.ValidationError(
                {"api_key": "API key is required for a new provider."}
            )
        return data


# ---------------------------------------------------------------------------
# Xero Error Serializers
# ---------------------------------------------------------------------------


class XeroErrorSerializer(serializers.ModelSerializer):
    """
    Basic serializer to expose all fields of XeroError.

    This is required by apps that import `XeroErrorSerializer`
    (e.g., `apps.workflow.views.xero.xero_view`).
    """

    class Meta:
        model = XeroError
        fields = "__all__"


class XeroErrorListResponseSerializer(serializers.Serializer):
    """Serializer for paginated Xero error list response."""

    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = XeroErrorSerializer(many=True)


class XeroErrorDetailResponseSerializer(serializers.Serializer):
    """Serializer for single Xero error detail response."""

    # Uses all the fields from XeroErrorSerializer
    id = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    entity = serializers.CharField()
    operation = serializers.CharField()
    error_type = serializers.CharField()
    error_message = serializers.CharField()
    xero_id = serializers.CharField(allow_null=True)
    context = serializers.JSONField()


class XeroAuthenticationErrorResponseSerializer(serializers.Serializer):
    """Serializer for Xero authentication error responses."""

    success = serializers.BooleanField(default=False)
    redirect_to_auth = serializers.BooleanField(default=True)
    message = serializers.CharField()


class XeroOperationResponseSerializer(serializers.Serializer):
    """Serializer for Xero operation responses (create/delete)."""

    success = serializers.BooleanField()
    error = serializers.CharField(required=False)
    messages = serializers.ListField(child=serializers.CharField(), required=False)
    online_url = serializers.URLField(required=False, allow_blank=True)
    xero_id = serializers.UUIDField(required=True)


class XeroQuoteCreateSerializer(serializers.Serializer):
    """
    Request serializer for creating a Xero quote.
    Requires explicit choice of breakdown format.
    """

    breakdown = serializers.BooleanField(
        required=True,
        help_text="If true, sends detailed line items. If false, sends single total line.",
    )


class XeroDocumentSuccessResponseSerializer(serializers.Serializer):
    """
    Standardized serializer for a successful Xero document operation.
    """

    success = serializers.BooleanField(default=True)
    xero_id = serializers.UUIDField(
        help_text="The Xero UUID of the created/modified document."
    )
    online_url = serializers.URLField(
        help_text="Direct link to the document in Xero.",
        allow_blank=True,
        required=False,
    )
    messages = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Informational messages.",
    )

    # Fields returned by Invoice/Quote managers
    client = serializers.CharField(required=False, help_text="Name of the client.")
    total_excl_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )
    total_incl_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )

    # Fields returned by PO manager
    action = serializers.CharField(
        required=False,
        help_text="The action performed (e.g., 'created', 'updated', 'deleted').",
    )


class XeroDocumentErrorResponseSerializer(serializers.Serializer):
    """
    Standardized serializer for a failed Xero document operation.
    """

    success = serializers.BooleanField(default=False)
    error = serializers.CharField(help_text="A description of the error that occurred.")
    messages = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Contextual error messages.",
    )
    error_type = serializers.CharField(
        required=False,
        help_text="A machine-readable error type (e.g., 'validation_error').",
    )
    redirect_to_auth = serializers.BooleanField(
        required=False, help_text="Indicates if re-authentication is needed."
    )


class XeroSseEventSerializer(serializers.Serializer):
    """Serializer for Xero SSE event data."""

    datetime = serializers.DateTimeField()
    message = serializers.CharField()
    severity = serializers.ChoiceField(
        choices=[("info", "info"), ("warning", "warning"), ("error", "error")],
        required=False,
        allow_null=True,
    )
    entity = serializers.CharField(required=False, allow_null=True)
    progress = serializers.FloatField(required=False, allow_null=True)
    overall_progress = serializers.FloatField(required=False, allow_null=True)
    entity_progress = serializers.FloatField(required=False, allow_null=True)
    records_updated = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_null=True)
    sync_status = serializers.ChoiceField(
        choices=[("success", "success"), ("error", "error"), ("running", "running")],
        required=False,
        allow_null=True,
    )
    error_messages = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    missing_fields = serializers.ListField(
        child=serializers.CharField(), required=False
    )


class XeroSyncInfoResponseSerializer(serializers.Serializer):
    """Serializer for Xero sync info response."""

    last_syncs = serializers.DictField()
    sync_range = serializers.CharField()
    sync_in_progress = serializers.BooleanField()
    error = serializers.CharField(required=False)
    redirect_to_auth = serializers.BooleanField(required=False)


class XeroSyncStartResponseSerializer(serializers.Serializer):
    """Serializer for start Xero sync response."""

    status = serializers.CharField()
    message = serializers.CharField()
    task_id = serializers.CharField(required=False)
    error = serializers.CharField(required=False)


class XeroTriggerSyncResponseSerializer(serializers.Serializer):
    """Serializer for trigger Xero sync response."""

    success = serializers.BooleanField()
    task_id = serializers.CharField(required=False)
    started = serializers.BooleanField(required=False)
    message = serializers.CharField(required=False)


class XeroPingResponseSerializer(serializers.Serializer):
    """Serializer for Xero ping response."""

    connected = serializers.BooleanField()


# ---------------------------------------------------------------------------
# App Error Serializers
# ---------------------------------------------------------------------------


class AppErrorSerializer(serializers.ModelSerializer):
    """Basic serializer for AppError instances."""

    class Meta:
        model = AppError
        fields = "__all__"


class AppErrorListResponseSerializer(serializers.Serializer):
    """Serializer for paginated AppError list response."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = AppErrorSerializer(many=True)


class AppErrorDetailResponseSerializer(serializers.Serializer):
    """Serializer for single AppError detail response."""

    id = serializers.UUIDField()
    timestamp = serializers.DateTimeField()
    message = serializers.CharField()
    data = serializers.JSONField()
    app = serializers.CharField(allow_null=True)
    file = serializers.CharField(allow_null=True)
    function = serializers.CharField(allow_null=True)
    severity = serializers.IntegerField()
    job_id = serializers.UUIDField(allow_null=True)
    user_id = serializers.UUIDField(allow_null=True)
    resolved = serializers.BooleanField()
    resolved_by = serializers.UUIDField(allow_null=True)
    resolved_timestamp = serializers.DateTimeField(allow_null=True)



# ---------------------------------------------------------------------------
# Company Defaults Schema Serializers
# ---------------------------------------------------------------------------


class SettingsFieldSerializer(serializers.Serializer):
    """Serializer for individual field metadata."""

    key = serializers.CharField()
    label = serializers.CharField()
    type = serializers.CharField()
    required = serializers.BooleanField()
    help_text = serializers.CharField(allow_blank=True)
    section = serializers.CharField()
    read_only = serializers.BooleanField()


class SettingsSectionSerializer(serializers.Serializer):
    """Serializer for a section containing fields."""

    key = serializers.CharField()
    title = serializers.CharField()
    order = serializers.IntegerField()
    fields = SettingsFieldSerializer(many=True)


class CompanyDefaultsSchemaSerializer(serializers.Serializer):
    """Serializer for the complete schema response."""

    sections = SettingsSectionSerializer(many=True)
