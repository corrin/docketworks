"""Call accounting includes fractional-dollar spend and cached input discounts."""

from decimal import Decimal
from unittest.mock import patch

import litellm
import pytest
from agents import Agent, RunContextWrapper
from agents.items import ModelResponse
from agents.usage import Usage
from asgiref.sync import async_to_sync

from apps.ai.services.llm_client import AgentCallRecording, LLMTarget, chat_completion
from apps.platform.observability.models import VendorCall

pytestmark = pytest.mark.django_db


def test_records_tokens_cost_and_wall_time() -> None:
    target = LLMTarget(model="openai/gpt-4o", api_key="k", provider_name="OpenAI")
    response = litellm.ModelResponse(
        model=target.model,
        choices=[{"message": {"role": "assistant", "content": "answer"}}],
        usage=litellm.Usage(prompt_tokens=120, completion_tokens=34, total_tokens=154),
    )
    with (
        patch("apps.ai.services.llm_client.resolve_target", return_value=target),
        patch("litellm.completion", return_value=response),
        patch("apps.ai.services.llm_client.time.perf_counter", side_effect=[10.0, 11.25]),
    ):
        assert chat_completion("hello") == "answer"

    row = VendorCall.objects.get()
    assert row.vendor == VendorCall.Vendor.LLM
    assert row.tokens_in == 120
    assert row.tokens_out == 34
    assert row.model_name == target.model
    assert row.estimated_cost_usd == Decimal("0.00064")
    assert row.duration_ms == 1250
    assert row.day_remaining is None


@pytest.mark.parametrize(
    ("model", "cache_write_tokens", "expected_cost"),
    [
        ("openai/gpt-4o", 0, Decimal("0.000515")),
        ("claude-sonnet-4-20250514", 10, Decimal("0.0006075")),
    ],
)
def test_streamed_usage_applies_cached_input_discount(
    model: str, cache_write_tokens: int, expected_cost: Decimal
) -> None:
    """Cached input must not be billed again at the full input-token rate."""
    target = LLMTarget(model=model, api_key="k", provider_name="Test provider")
    hook = AgentCallRecording[None](target)
    context = RunContextWrapper(context=None)
    agent = Agent[None](name="Accounting test")
    usage = Usage(input_tokens=120, output_tokens=34, total_tokens=154)
    usage.input_tokens_details.cached_tokens = 100
    usage.input_tokens_details.cache_write_tokens = cache_write_tokens
    response = ModelResponse(
        output=[],
        response_id=None,
        usage=usage,
    )
    with patch("apps.ai.services.llm_client.time.perf_counter", side_effect=[10.0, 11.25]):
        async_to_sync(hook.on_llm_start)(context, agent, None, [])
        async_to_sync(hook.on_llm_end)(context, agent, response)

    row = VendorCall.objects.get()
    assert row.tokens_in == 120
    assert row.tokens_out == 34
    assert row.estimated_cost_usd == expected_cost
    assert row.duration_ms == 1250
