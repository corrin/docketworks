"""CLI scenario helpers using the production ChatKit conversation pipeline."""

from asgiref.sync import async_to_sync
from chatkit.types import AssistantMessageItem, UserMessageItem, UserMessageTextContent

from apps.job.chat.conversation import send_message as send_chat_message
from apps.job.chat.store import ITEM_ADAPTER, ChatContext
from apps.job.models import Job, JobQuoteChat, JobQuoteChatThread


def send_message(job: Job, content: str) -> str:
    """Continue this job's newest conversation through ChatKit."""
    thread = JobQuoteChatThread.objects.filter(job=job).order_by("-created_at", "-id").first()
    thread_id = thread.id if thread is not None else None
    return async_to_sync(send_chat_message)(ChatContext(job_id=job.id), content, thread_id)


def clear_chat(job: Job) -> int:
    """Delete this scenario's existing conversations and their items."""
    deleted, _by_model = JobQuoteChatThread.objects.filter(job=job).delete()
    return deleted


def print_history(job: Job) -> int:
    """Print text from the persisted SDK items; workflow items remain in storage."""
    messages = JobQuoteChat.objects.filter(thread__job=job).order_by("timestamp", "message_id")
    for row in messages:
        item = ITEM_ADAPTER.validate_python(row.payload)
        if isinstance(item, AssistantMessageItem):
            print("AI:", "\n".join(part.text for part in item.content))
        elif isinstance(item, UserMessageItem):
            print(
                "User:",
                "\n".join(
                    part.text for part in item.content if isinstance(part, UserMessageTextContent)
                ),
            )
    return messages.count()
