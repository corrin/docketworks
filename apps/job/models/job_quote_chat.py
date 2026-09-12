"""Durable job-scoped ChatKit conversations and protocol items."""

import uuid
from typing import ClassVar

from django.db import models

from .job import Job


class JobQuoteChatThread(models.Model):
    """One conversation, including the SDK's server-side metadata."""

    id = models.CharField(primary_key=True, max_length=100)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="quote_chat_threads")
    created_at = models.DateTimeField()
    payload = models.JSONField()

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at", "id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["job", "created_at", "id"], name="job_chat_thread_created_idx")
        ]

    def __str__(self) -> str:
        return self.id


class JobQuoteChat(models.Model):
    """One SDK item, retaining the existing message table and identifiers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(JobQuoteChatThread, on_delete=models.CASCADE, related_name="items")
    message_id = models.CharField(max_length=100, unique=True)
    timestamp = models.DateTimeField()
    payload = models.JSONField()

    class Meta:
        ordering: ClassVar[list[str]] = ["timestamp", "message_id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["thread", "timestamp", "message_id"], name="job_chat_item_created_idx"
            ),
        ]

    def __str__(self) -> str:
        return self.message_id
