"""Shared plumbing for the quote-chat harness scripts.

Used by scripts/ops/test_chat_conversation.py and
scripts/ops/test_full_quote_conversation.py: persist a user message on a
job's JobQuoteChat thread, generate the assistant reply through the single
LLM gateway (ADR 0041 — apps/ai's chat_completion; v1's vendor-SDK
GeminiChatService is not ported), and persist the reply.

The gateway takes one prompt string, so the conversation is rendered as a
transcript each turn. v1's CALC/PRICE/TABLE mode machinery lived in the
unported Gemini service and does not exist here; these harnesses exercise
persistence plus the gateway, not mode inference.

Importers must call django.setup() before importing this module.
"""

import uuid

from apps.ai.services.llm_client import chat_completion
from apps.job.models import Job, JobQuoteChat

PROMPT_PREAMBLE = (
    "You are a quoting assistant for a sheet-metal fabrication shop. "
    "Help the user calculate materials and build a quote. Be concise and "
    "concrete; ask for missing dimensions or materials when you need them.\n"
)


def build_transcript_prompt(job: Job, user_message: str) -> str:
    """Render the job context and stored chat history into one gateway prompt.

    The history is re-sent every turn because chat_completion takes a single
    user prompt, not a message list; context lives in the JobQuoteChat rows.
    """
    lines = [
        PROMPT_PREAMBLE,
        f"Job {job.job_number}: {job.name}",
        f"Customer: {job.company.name if job.company else 'unknown'}",
        "",
        "Conversation so far:",
    ]
    for msg in JobQuoteChat.objects.filter(job=job).order_by("timestamp"):
        role = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{role}: {msg.content}")
    lines.append(f"User: {user_message}")
    lines.append("")
    lines.append("Reply as the assistant.")
    return "\n".join(lines)


def send_message(job: Job, content: str) -> str:
    """Persist a user message, generate the assistant reply, persist it, return it.

    The prompt is built BEFORE the user row is saved so the message appears
    exactly once in what the model sees.
    """
    prompt = build_transcript_prompt(job, content)

    # message_id is globally unique across jobs, so fixed step names (v1's
    # "user-1") would collide with leftovers on other jobs; suffix each run.
    JobQuoteChat.objects.create(
        job=job,
        message_id=f"user-{uuid.uuid4().hex[:12]}",
        role="user",
        content=content,
    )

    reply = chat_completion(prompt)

    JobQuoteChat.objects.create(
        job=job,
        message_id=f"assistant-{uuid.uuid4().hex[:12]}",
        role="assistant",
        content=reply,
    )
    return reply


def clear_chat(job: Job) -> int:
    """Delete the job's existing chat rows for a clean run; returns the count."""
    deleted, _by_model = JobQuoteChat.objects.filter(job=job).delete()
    return deleted


def print_history(job: Job) -> int:
    """Print the stored conversation; returns the message count."""
    messages = JobQuoteChat.objects.filter(job=job).order_by("timestamp")
    for msg in messages:
        role = "User" if msg.role == "user" else "AI"
        print(f"{role}: {msg.content[:100]}")
        if len(msg.content) > 100:
            print(f"      ... (truncated from {len(msg.content)} chars)")
    return messages.count()
