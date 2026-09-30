"""Call accounting records fractional-dollar spend and persists a pricing failure."""

from decimal import Decimal
from unittest.mock import patch

import litellm
import pytest

from apps.ai.services.llm_client import LLMTarget, chat_completion
from apps.core.models import AppError
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


def test_an_unpriced_model_still_records_the_call() -> None:
    """A model LiteLLM cannot price is the case metering exists for; the row must survive."""
    target = LLMTarget(model="openai/gpt-brand-new", api_key="k", provider_name="OpenAI")
    response = litellm.ModelResponse(
        model=target.model,
        choices=[{"message": {"role": "assistant", "content": "answer"}}],
        usage=litellm.Usage(prompt_tokens=120, completion_tokens=34, total_tokens=154),
    )
    with (
        patch("apps.ai.services.llm_client.resolve_target", return_value=target),
        patch("litellm.completion", return_value=response),
        patch("litellm.cost_per_token", side_effect=Exception("Unable to calculate cost")),
    ):
        assert chat_completion("hello") == "answer"

    row = VendorCall.objects.get()
    assert row.tokens_in == 120
    assert row.estimated_cost_usd is None
    assert AppError.objects.filter(message__contains="Unable to calculate cost").exists()
