import uuid

from django.db import models

from .job import Job


class JobQuoteChat(models.Model):
    """
    Stores chat messages for the interactive quoting feature linked to jobs.
    Each job can have an associated chat conversation where users interact
    with an LLM to generate quotes.
    """

    # CHECKLIST - when adding a new field or property to JobQuoteChat, check these locations:
    #   1. JOBQUOTECHAT_API_FIELDS or JOBQUOTECHAT_INTERNAL_FIELDS below (if it's a model field)
    #   2. JobQuoteChatSerializer in apps/job/serializers/job_quote_chat_serializer.py (read)
    #   3. JobQuoteChatCreateSerializer in apps/job/serializers/job_quote_chat_serializer.py (write)
    #   4. JobQuoteChatUpdateSerializer in apps/job/serializers/job_quote_chat_serializer.py (patch)
    #   5. JobQuoteChatViewSet in apps/job/views/job_quote_chat_views.py (CRUD operations)
    #   6. ChatService in apps/job/services/chat_service.py (AI chat logic)
    #
    # Database fields exposed via API serializers
    JOBQUOTECHAT_API_FIELDS = [
        "message_id",
        "role",
        "content",
        "metadata",
        "timestamp",
    ]

    # Internal fields not exposed in API
    JOBQUOTECHAT_INTERNAL_FIELDS = [
        "id",
        "job",
    ]

    # All JobQuoteChat model fields (derived)
    JOBQUOTECHAT_ALL_FIELDS = JOBQUOTECHAT_API_FIELDS + JOBQUOTECHAT_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, related_name="quote_chat_messages"
    )
    message_id = models.CharField(
        max_length=100, unique=True, help_text="Frontend-generated unique ID"
    )

    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra data like streaming status, processing time, etc.",
    )

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["job", "timestamp"]),
            models.Index(fields=["message_id"]),
        ]

    def __str__(self):
        return f"{self.job.name} - {self.role}: {self.content}"
