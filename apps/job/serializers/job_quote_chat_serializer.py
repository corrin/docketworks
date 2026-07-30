from rest_framework import serializers

from apps.job.models import JobQuoteChat
from apps.workflow.serializers_base import NullUnsetModelSerializer


class JobQuoteChatCreateSerializer(NullUnsetModelSerializer[JobQuoteChat]):
    """
    Serializer for creating new JobQuoteChat messages.
    Validates required fields and business rules.
    """

    class Meta:
        model = JobQuoteChat
        # Write subset: API fields except timestamp (auto-generated)
        fields = ["message_id", "role", "content", "metadata"]
        extra_kwargs = {
            "metadata": {"default": dict, "required": False},
        }

    def validate_role(self, value):
        """Validate that role is either 'user' or 'assistant'."""
        if value not in ["user", "assistant"]:
            raise serializers.ValidationError(
                "Role must be either 'user' or 'assistant'"
            )
        return value

    def validate_message_id(self, value):
        """Validate that message_id is provided and unique for this job."""
        if not value.strip():
            raise serializers.ValidationError("Message ID cannot be empty")
        return value


class JobQuoteChatSerializer(NullUnsetModelSerializer[JobQuoteChat]):
    """
    Serializer for JobQuoteChat responses (includes timestamp).
    Used when returning saved messages to the client.
    """

    class Meta:
        model = JobQuoteChat
        fields = JobQuoteChat.JOBQUOTECHAT_API_FIELDS
        read_only_fields = ["timestamp"]
        extra_kwargs = {
            "metadata": {"default": dict, "required": False},
        }


class JobQuoteChatUpdateSerializer(NullUnsetModelSerializer[JobQuoteChat]):
    """
    Serializer for updating existing JobQuoteChat messages.
    Used for PATCH operations, especially streaming response updates.
    """

    class Meta:
        model = JobQuoteChat
        fields = ["content", "metadata"]
        extra_kwargs = {"content": {"required": False}, "metadata": {"required": False}}

    def update(self, instance, validated_data):
        """Update instance with proper metadata merging."""
        # Update content if provided
        if "content" in validated_data:
            instance.content = validated_data["content"]

        # Merge metadata instead of replacing
        if "metadata" in validated_data:
            current_metadata = instance.metadata or {}
            current_metadata.update(validated_data["metadata"])
            instance.metadata = current_metadata

        instance.save()
        return instance


class JobQuoteChatMessageResponseSerializer(serializers.Serializer):
    """Serializer for individual chat message in responses."""

    message_id = serializers.CharField()
    role = serializers.ChoiceField(
        choices=[("user", "User"), ("assistant", "Assistant")]
    )
    content = serializers.CharField()
    timestamp = serializers.DateTimeField()
    metadata = serializers.JSONField()


class JobQuoteChatHistoryResponseSerializer(serializers.Serializer):
    """Serializer for chat history response."""

    success = serializers.BooleanField()
    data = serializers.DictField()

    def to_representation(self, instance):
        """Custom representation to handle nested messages."""
        data = super().to_representation(instance)
        if "data" in data and "messages" in data["data"]:
            # Serialize messages using the message serializer
            messages_data = data["data"]["messages"]
            serialized_messages = JobQuoteChatMessageResponseSerializer(
                messages_data, many=True
            ).data
            data["data"]["messages"] = serialized_messages
        return data


class JobQuoteChatCreateResponseSerializer(serializers.Serializer):
    """Serializer for chat message creation response."""

    success = serializers.BooleanField()
    data = serializers.DictField()


class JobQuoteChatDeleteResponseSerializer(serializers.Serializer):
    """Serializer for chat deletion response."""

    success = serializers.BooleanField()
    data = serializers.DictField()


class JobQuoteChatUpdateResponseSerializer(serializers.Serializer):
    """Serializer for chat message update response."""

    success = serializers.BooleanField()
    data = serializers.DictField()


class JobQuoteChatInteractionSerializer(serializers.Serializer):
    """Serializer for chat interaction request data."""

    message = serializers.CharField(
        max_length=5000,
        help_text="User message content to send to the AI assistant",
    )
    mode = serializers.ChoiceField(
        choices=["CALC", "PRICE", "TABLE", "AUTO"],
        required=False,
        default="AUTO",
        help_text="Operation mode: CALC for calculations, PRICE for pricing, TABLE for summaries, AUTO for automatic detection",
    )


class JobQuoteChatInteractionSuccessResponseSerializer(serializers.Serializer):
    """Serializer for successful chat interaction response."""

    success = serializers.BooleanField(default=True)
    data = JobQuoteChatSerializer()


class JobQuoteChatInteractionErrorResponseSerializer(serializers.Serializer):
    """Serializer for error chat interaction response."""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
    code = serializers.CharField(
        required=False, help_text="Error code for specific error types"
    )
