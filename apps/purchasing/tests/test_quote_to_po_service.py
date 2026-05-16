"""Quote-to-PO extraction coverage (Trello #325 — anthropic SDK transition)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.purchasing.services.quote_to_po_service import (
    extract_data_from_supplier_quote,
)
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider


@pytest.fixture
def anthropic_provider(db):
    return AIProvider.objects.create(
        name="Test Claude",
        provider_type=AIProviderTypes.ANTHROPIC,
        api_key="test-key",
        model_name="claude-test-model",
        default=True,
    )


def test_extract_uses_sdk_and_parses_response(anthropic_provider, tmp_path):
    """SDK path: prompt + file go through messages.create, JSON response parses."""
    quote_text = "Quote QX-1: 2x 100mm SHS @ $50.00"
    quote_path = tmp_path / "quote.txt"
    quote_path.write_text(quote_text)

    payload = {
        "supplier": {"name": "Acme Metals"},
        "quote_reference": "QX-1",
        "items": [
            {
                "description": "100mm SHS",
                "quantity": 2,
                "line_total": 100.00,
                "unit_price": "50.00",
                "supplier_item_code": "SHS-100",
                "metal_type": "mild_steel",
            }
        ],
    }
    mock_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch(
        "apps.purchasing.services.quote_to_po_service.anthropic.Anthropic",
        return_value=mock_client,
    ) as mock_ctor:
        quote_data, error = extract_data_from_supplier_quote(
            str(quote_path), content_type="text/plain"
        )

    assert error is None
    assert quote_data["supplier"]["name"] == "Acme Metals"
    assert quote_data["quote_reference"] == "QX-1"
    assert len(quote_data["items"]) == 1
    assert quote_data["items"][0]["description"] == "100mm SHS"

    mock_ctor.assert_called_once_with(api_key="test-key")
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-test-model"
    assert call_kwargs["max_tokens"] == 4000
    prompt_block = call_kwargs["messages"][0]["content"][0]
    assert prompt_block["type"] == "text"
    assert prompt_block["cache_control"] == {"type": "ephemeral"}
