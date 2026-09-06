"""The CLI uses the persisted chat pipeline and rejects invalid scope before a model call."""

from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai.models import AIProvider
from apps.core.models import AppError
from apps.job.models import Job, JobQuoteChat

pytestmark = pytest.mark.django_db


def test_missing_job_is_refused() -> None:
    """Reject invalid job scope before invoking the conversation pipeline."""
    missing_id = str(uuid4())
    with pytest.raises(CommandError, match="does not exist"):
        call_command("ai_chat_harness", missing_id, "hello", stdout=StringIO())
    assert JobQuoteChat.objects.count() == 0


def test_configuration_failure_preserves_the_user_message_for_retry(job: Job) -> None:
    """An unavailable provider must not discard the operator's submitted message."""
    AIProvider.objects.all().delete()
    with pytest.raises(RuntimeError, match="No AI provider of type OpenAI"):
        call_command("ai_chat_harness", str(job.id), "Quote a bench", stdout=StringIO())
    assert JobQuoteChat.objects.filter(thread__job=job, payload__type="user_message").count() == 1
    assert AppError.objects.count() == 0


def test_invalid_provider_argument_does_not_create_a_conversation(job: Job) -> None:
    """Validate CLI provider selection before any conversation writes."""
    with pytest.raises(CommandError, match="invalid choice"):
        call_command("ai_chat_harness", str(job.id), "hello", "--provider-type", "banana")
    assert JobQuoteChat.objects.count() == 0
