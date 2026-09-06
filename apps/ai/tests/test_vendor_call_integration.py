"""LLM completions reach the vendor-call log (ADR 0050).

The token counts are the vendor's own, so a fake would only confirm what we
already believed about its tokeniser — which is the thing worth checking rather
than recording. ADR 0041 puts token accounting at this boundary; this proves it
arrives.
"""

import pytest

from apps.ai.services.llm_client import chat_completion
from apps.platform.observability.models import VendorCall

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def _credentials(integration_credentials: None) -> None:
    """Bring the AI provider credentials across from the dev database (ADR 0050)."""


def test_a_real_completion_records_the_tokens_the_vendor_counted() -> None:
    VendorCall.objects.all().delete()

    # Structure, not content: the model is free to word this how it likes
    # (ADR 0050). What is asserted is that real usage came back and landed.
    chat_completion("Reply with the single word: ready.")

    row = VendorCall.objects.get(vendor=VendorCall.Vendor.LLM)
    assert row.tokens_in is not None and row.tokens_in > 0
    assert row.tokens_out is not None and row.tokens_out > 0
    assert row.model_name
    assert row.duration_ms >= 0
