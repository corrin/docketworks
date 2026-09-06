"""What the LLM gateway writes to the vendor-call log.

ADR 0041 puts token accounting at this one boundary. Nothing reads these counts
at runtime, so a change to litellm handling that dropped them would otherwise
be invisible until someone asked what AI had cost.
"""

from unittest.mock import MagicMock, patch

import pytest

from apps.ai.services.llm_client import LLMTarget, chat_completion
from apps.platform.observability.models import VendorCall

pytestmark = pytest.mark.django_db


def _response(*, prompt_tokens: int, completion_tokens: int) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = "answer"
    response.usage.prompt_tokens = prompt_tokens
    response.usage.completion_tokens = completion_tokens
    return response


def test_records_the_tokens_the_vendor_reported() -> None:
    target = LLMTarget(model="gemini/flash", api_key="k", provider_name="Google")
    with (
        patch("apps.ai.services.llm_client.resolve_target", return_value=target),
        patch(
            "litellm.completion", return_value=_response(prompt_tokens=120, completion_tokens=34)
        ),
    ):
        assert chat_completion("hello") == "answer"

    row = VendorCall.objects.get()
    assert row.vendor == VendorCall.Vendor.LLM
    assert row.tokens_in == 120
    assert row.tokens_out == 34
    assert row.model_name == "gemini/flash"
    # No quota meter: the gateway reports usage, not a remaining balance.
    assert row.day_remaining is None
