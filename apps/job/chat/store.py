"""The ChatKit storage contract, with job scope checked on every operation."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from chatkit.store import NotFoundError, Store
from chatkit.types import Attachment, Page, ThreadItem, ThreadMetadata
from django.db.models import Q
from django.utils import timezone
from pydantic import TypeAdapter

from apps.job.models import JobQuoteChat, JobQuoteChatThread

ITEM_ADAPTER: TypeAdapter[ThreadItem] = TypeAdapter(ThreadItem)


@dataclass(frozen=True)
class ChatContext:
    """Trusted request scope, constructed only after staff authentication."""

    job_id: UUID
    provider_type: str | None = None


class JobChatStore(Store[ChatContext]):
    """Persist the SDK's payloads without maintaining a competing message schema."""

    async def load_thread(self, thread_id: str, context: ChatContext) -> ThreadMetadata:
        """Read metadata only within the authenticated job."""
        try:
            row = await JobQuoteChatThread.objects.aget(id=thread_id, job_id=context.job_id)
        except JobQuoteChatThread.DoesNotExist as exc:
            raise NotFoundError("Conversation not found in this job") from exc
        return ThreadMetadata.model_validate(row.payload)

    async def save_thread(self, thread: ThreadMetadata, context: ChatContext) -> None:
        """Create or update scoped metadata; a foreign job's id cannot be reassigned."""
        await JobQuoteChatThread.objects.aupdate_or_create(
            id=thread.id,
            job_id=context.job_id,
            defaults={
                "created_at": storage_timestamp(thread.created_at),
                "payload": thread.model_dump(mode="json"),
            },
        )

    async def load_threads(
        self, limit: int, after: str | None, order: str, context: ChatContext
    ) -> Page[ThreadMetadata]:
        """Page conversations using stable timestamp/id ordering."""
        rows = JobQuoteChatThread.objects.filter(job_id=context.job_id)
        descending = order == "desc"
        if after is not None:
            cursor = await self.load_thread(after, context)
            operator = "lt" if descending else "gt"
            rows = rows.filter(
                Q(**{f"created_at__{operator}": storage_timestamp(cursor.created_at)})
                | Q(
                    created_at=storage_timestamp(cursor.created_at),
                    **{f"id__{operator}": cursor.id},
                )
            )
        ordering = ("-created_at", "-id") if descending else ("created_at", "id")
        found = [row async for row in rows.order_by(*ordering)[: limit + 1]]
        data = [ThreadMetadata.model_validate(row.payload) for row in found[:limit]]
        return Page(data=data, has_more=len(found) > limit, after=data[-1].id if data else None)

    async def load_thread_items(
        self, thread_id: str, after: str | None, limit: int, order: str, context: ChatContext
    ) -> Page[ThreadItem]:
        """Page items without loading the entire job's conversation history."""
        await self.load_thread(thread_id, context)
        rows = JobQuoteChat.objects.filter(thread_id=thread_id)
        descending = order == "desc"
        if after is not None:
            cursor = await self.load_item(thread_id, after, context)
            operator = "lt" if descending else "gt"
            rows = rows.filter(
                Q(**{f"timestamp__{operator}": storage_timestamp(cursor.created_at)})
                | Q(
                    timestamp=storage_timestamp(cursor.created_at),
                    **{f"message_id__{operator}": cursor.id},
                )
            )
        ordering = ("-timestamp", "-message_id") if descending else ("timestamp", "message_id")
        found = [row async for row in rows.order_by(*ordering)[: limit + 1]]
        data = [ITEM_ADAPTER.validate_python(row.payload) for row in found[:limit]]
        return Page(data=data, has_more=len(found) > limit, after=data[-1].id if data else None)

    async def add_thread_item(self, thread_id: str, item: ThreadItem, context: ChatContext) -> None:
        """Insert an item only into the thread named by its own payload."""
        await self.save_item(thread_id, item, context)

    async def save_item(self, thread_id: str, item: ThreadItem, context: ChatContext) -> None:
        """Upsert the protocol item after checking both thread scope and identity."""
        await self.load_thread(thread_id, context)
        if item.thread_id != thread_id:
            raise ValueError("Item does not belong to the requested conversation")
        await JobQuoteChat.objects.aupdate_or_create(
            thread_id=thread_id,
            message_id=item.id,
            defaults={
                "timestamp": storage_timestamp(item.created_at),
                "payload": item.model_dump(mode="json"),
            },
        )

    async def load_item(self, thread_id: str, item_id: str, context: ChatContext) -> ThreadItem:
        """Read a single item with no cross-job identifier lookup."""
        await self.load_thread(thread_id, context)
        try:
            row = await JobQuoteChat.objects.aget(thread_id=thread_id, message_id=item_id)
        except JobQuoteChat.DoesNotExist as exc:
            raise NotFoundError("Message not found in this conversation") from exc
        return ITEM_ADAPTER.validate_python(row.payload)

    async def delete_thread(self, thread_id: str, context: ChatContext) -> None:
        """Delete a scoped conversation and its items together."""
        await self.load_thread(thread_id, context)
        await JobQuoteChatThread.objects.filter(id=thread_id, job_id=context.job_id).adelete()

    async def delete_thread_item(self, thread_id: str, item_id: str, context: ChatContext) -> None:
        """Delete only an item in the requested conversation."""
        await self.load_thread(thread_id, context)
        await JobQuoteChat.objects.filter(thread_id=thread_id, message_id=item_id).adelete()

    async def save_attachment(self, attachment: Attachment, context: ChatContext) -> None:
        """Refuse uploads; this integration exposes no attachment capability."""
        raise ValueError(f"Attachment {attachment.id} cannot be saved for job {context.job_id}")

    async def load_attachment(self, attachment_id: str, context: ChatContext) -> Attachment:
        """Reject attachment references as well as uploads."""
        raise NotFoundError(f"Attachment {attachment_id} not found in job {context.job_id}")

    async def delete_attachment(self, attachment_id: str, context: ChatContext) -> None:
        """Refuse attachment operations consistently."""
        raise NotFoundError(f"Attachment {attachment_id} not found in job {context.job_id}")


def storage_timestamp(value: datetime) -> datetime:
    """Translate SDK process-local timestamps to Django-aware database values."""
    # GPT: ChatKit 1.6 uses datetime.now(); imported legacy messages are already aware.
    # Its workflow duration calculations require retaining the SDK timestamp in its payload.
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_default_timezone())
    return value
