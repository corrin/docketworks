"""The ai_chat_harness command: prompt assembly, gateway routing, refusals.

The LLM gateway is the only mocked seam (ADR 0041), patched where the command
bound ``chat_completion`` at import — patching ``apps.ai.services.llm_client``
would leave the command's own reference calling litellm for real.
"""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai.services.llm_client import LLMConfigurationError
from apps.core.models import AppError
from apps.job.management.commands import ai_chat_harness as harness_module
from apps.job.management.commands.ai_chat_harness import build_prompt
from apps.job.models import Job, JobQuoteChat

pytestmark = pytest.mark.django_db


def _run(*args: str) -> str:
    out = StringIO()
    call_command("ai_chat_harness", *args, stdout=out)
    return out.getvalue()


def _make_message(job: Job, message_id: str, role: str, content: str) -> JobQuoteChat:
    return JobQuoteChat.objects.create(job=job, message_id=message_id, role=role, content=content)


class GatewayRecorder:
    """A fake gateway that records each prompt/provider pair and answers fixedly."""

    def __init__(self, reply: str = "A fabricated model reply") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, prompt: str, *, provider_type: str | None = None) -> str:
        self.calls.append((prompt, provider_type))
        return self.reply


class RaisingGateway(GatewayRecorder):
    """A fake gateway whose every completion fails with the given exception."""

    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def __call__(self, prompt: str, *, provider_type: str | None = None) -> str:
        super().__call__(prompt, provider_type=provider_type)
        raise self.exc


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> GatewayRecorder:
    recorder = GatewayRecorder()
    monkeypatch.setattr(harness_module, "chat_completion", recorder)
    return recorder


def test_missing_job_is_refused() -> None:
    missing_id = str(uuid.uuid4())

    with pytest.raises(CommandError, match=f'Job with ID "{missing_id}" does not exist.'):
        _run(missing_id, "hello")


def test_reply_printed_and_stored_history_reaches_the_prompt(
    job: Job, gateway: GatewayRecorder
) -> None:
    Job.objects.filter(pk=job.pk).untracked_update(description="Stainless bench, 2m run")
    _make_message(job, "m-1", "user", "Can you quote a bench?")
    _make_message(job, "m-2", "assistant", "What material?")

    output = _run(str(job.id), "Stainless, please")

    assert "Stored history messages: 2" in output
    assert "A fabricated model reply" in output
    assert "--- End response ---" in output
    (prompt, provider_type) = gateway.calls[0]
    assert provider_type is None
    assert "Job: Fixture Job" in prompt
    assert "Job description: Stainless bench, 2m run" in prompt
    assert "user: Can you quote a bench?" in prompt
    assert "assistant: What material?" in prompt
    assert prompt.endswith("user: Stainless, please")
    # A debugging probe, not a mutation: the exchange is never persisted.
    assert JobQuoteChat.objects.filter(job=job).count() == 2


def test_provider_override_is_forwarded_to_the_gateway(job: Job, gateway: GatewayRecorder) -> None:
    _run(str(job.id), "hello", "--provider-type", "Gemini")

    assert gateway.calls[0][1] == "Gemini"


def test_unknown_provider_type_is_refused(job: Job, gateway: GatewayRecorder) -> None:
    with pytest.raises(CommandError, match="invalid choice"):
        _run(str(job.id), "hello", "--provider-type", "banana")
    assert gateway.calls == []


def test_configuration_error_becomes_operator_refusal(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        harness_module,
        "chat_completion",
        RaisingGateway(LLMConfigurationError("no default AI provider is configured")),
    )

    with pytest.raises(
        CommandError, match="AI provider configuration error: no default AI provider"
    ):
        _run(str(job.id), "hello")
    # An expected refusal, not an incident: nothing is persisted.
    assert AppError.objects.count() == 0


def test_unexpected_gateway_failure_is_persisted_and_reraised(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        harness_module, "chat_completion", RaisingGateway(RuntimeError("gateway exploded"))
    )

    with pytest.raises(RuntimeError, match="gateway exploded"):
        _run(str(job.id), "hello")
    assert AppError.objects.count() == 1


def test_prompt_without_description_or_history_omits_those_sections() -> None:
    prompt = build_prompt(Job(name="Bare Job"), [], "First question")

    assert "Job: Bare Job" in prompt
    assert "Job description:" not in prompt
    assert "Conversation so far:" not in prompt
    assert prompt.endswith("user: First question")
