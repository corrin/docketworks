"""Quote-to-PO extraction coverage (Trello #325 — anthropic SDK transition)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.client.models import Client
from apps.purchasing.models import PurchaseOrder, PurchaseOrderSupplierQuote
from apps.purchasing.services.quote_to_po_service import (
    SupplierQuoteItemModel,
    SupplierQuotePayloadModel,
    SupplierQuoteSupplierModel,
    create_po_from_quote,
    extract_data_from_supplier_quote,
)
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider


@pytest.fixture
def anthropic_provider(db: object) -> AIProvider:
    return AIProvider.objects.create(
        name="Test Claude",
        provider_type=AIProviderTypes.ANTHROPIC,
        api_key="test-key",
        model_name="claude-test-model",
        default=True,
    )


def test_extract_uses_sdk_and_parses_response(
    anthropic_provider: AIProvider, tmp_path: Path
) -> None:
    """SDK path: prompt + file go through messages.create, JSON response parses."""
    Client.objects.create(
        name="Acme Metals",
        xero_contact_id="xero-contact-1",
        xero_last_modified=timezone.now(),
        is_supplier=True,
    )
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
    assert quote_data is not None
    assert quote_data.supplier.name == "Acme Metals"
    assert quote_data.quote_reference == "QX-1"
    assert len(quote_data.line_items) == 1
    assert quote_data.line_items[0].description == "100mm SHS"
    assert quote_data.matched_supplier is not None
    assert quote_data.matched_supplier.xero_contact_id == "xero-contact-1"

    mock_ctor.assert_called_once_with(api_key="test-key")
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-test-model"
    assert call_kwargs["max_tokens"] == 4000
    prompt_block = call_kwargs["messages"][0]["content"][0]
    assert prompt_block["type"] == "text"
    assert prompt_block["cache_control"] == {"type": "ephemeral"}


def test_extract_pdf_parser_empty_text_falls_back_to_document(
    anthropic_provider: AIProvider, tmp_path: Path
) -> None:
    """Empty PDF text extraction preserves the original PDF document payload."""
    quote_path = tmp_path / "quote.pdf"
    quote_path.write_bytes(b"%PDF-1.7 fake pdf bytes")

    payload = {
        "supplier": {"name": "Acme Metals"},
        "quote_reference": "PDF-1",
        "items": [],
    }
    mock_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_page = MagicMock()
    mock_page.extract_text.return_value = ""
    mock_pdf = MagicMock()
    mock_pdf.__enter__.return_value.pages = [mock_page]

    with (
        patch(
            "apps.purchasing.services.quote_to_po_service.anthropic.Anthropic",
            return_value=mock_client,
        ),
        patch(
            "apps.purchasing.services.quote_to_po_service.pdfplumber.open",
            return_value=mock_pdf,
        ),
    ):
        quote_data, error = extract_data_from_supplier_quote(
            str(quote_path), content_type="application/pdf", use_pdf_parser=True
        )

    assert error is None
    assert quote_data is not None
    assert quote_data.quote_reference == "PDF-1"
    content_blocks = mock_client.messages.create.call_args.kwargs["messages"][0][
        "content"
    ]
    document_block = content_blocks[1]
    assert document_block["type"] == "document"
    assert document_block["source"]["type"] == "base64"
    assert document_block["source"]["media_type"] == "application/pdf"


@pytest.mark.parametrize(
    ("payload", "error_text"),
    [
        (
            {"supplier": "Acme Metals", "items": []},
            "supplier",
        ),
        (
            {"supplier": {"name": "Acme Metals"}, "items": {"description": "SHS"}},
            "items",
        ),
        (
            {"supplier": {"name": "Acme Metals"}, "items": ["SHS"]},
            "items.0",
        ),
        (
            {"supplier": {"name": 123}, "items": []},
            "supplier.name",
        ),
    ],
)
def test_extract_rejects_malformed_quote_payload_shape(
    anthropic_provider: AIProvider,
    tmp_path: Path,
    payload: object,
    error_text: str,
) -> None:
    quote_path = tmp_path / "quote.txt"
    quote_path.write_text("Quote text")
    mock_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch(
        "apps.purchasing.services.quote_to_po_service.anthropic.Anthropic",
        return_value=mock_client,
    ):
        quote_data, error = extract_data_from_supplier_quote(
            str(quote_path), content_type="text/plain"
        )

    assert quote_data is None
    assert error is not None
    assert error_text in error


def test_create_po_from_quote_saves_plain_json_payload(
    anthropic_provider: AIProvider,
) -> None:
    purchase_order = PurchaseOrder.objects.create(po_number="PO-QTP-1")
    quote = PurchaseOrderSupplierQuote.objects.create(
        purchase_order=purchase_order,
        filename="quote.txt",
        file_path="quote.txt",
        mime_type="text/plain",
    )
    quote_payload = SupplierQuotePayloadModel(
        supplier=SupplierQuoteSupplierModel(name="Acme Metals"),
        quote_reference="QX-1",
        items=[
            SupplierQuoteItemModel(
                description="100mm SHS",
                quantity=2,
                line_total=100.00,
                unit_price="50.00",
                supplier_item_code="SHS-100",
                metal_type="mild_steel",
            )
        ],
    )

    with patch(
        "apps.purchasing.services.quote_to_po_service.extract_data_from_supplier_quote",
        return_value=(quote_payload, None),
    ):
        result, error = create_po_from_quote(
            purchase_order,
            quote,
            anthropic_provider,
        )

    assert error is None
    assert result == purchase_order
    quote.refresh_from_db()
    assert quote.extracted_data == {
        "supplier": {"name": "Acme Metals"},
        "quote_reference": "QX-1",
        "items": [
            {
                "description": "100mm SHS",
                "quantity": 2,
                "unit_price": "50.00",
                "line_total": 100.0,
                "supplier_item_code": "SHS-100",
                "metal_type": "mild_steel",
            }
        ],
    }
    line = purchase_order.po_lines.get()
    assert line.raw_line_data == {
        "description": "100mm SHS",
        "quantity": 2,
        "unit_price": "50.00",
        "line_total": 100.0,
        "supplier_item_code": "SHS-100",
        "metal_type": "mild_steel",
    }
