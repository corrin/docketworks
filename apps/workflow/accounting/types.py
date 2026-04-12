"""Provider-agnostic data transfer types for the accounting abstraction layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class DocumentLineItem:
    """A single line item on an invoice, quote, or purchase order."""

    description: str
    quantity: Decimal
    unit_amount: Decimal
    account_code: str | None = None
    item_code: str | None = None


@dataclass
class InvoicePayload:
    """Data needed to create an invoice in any accounting system."""

    client_external_id: str
    client_name: str
    line_items: list[DocumentLineItem]
    date: date
    due_date: date
    currency_code: str = "NZD"
    reference: str | None = None
    url: str | None = None
    status: str = "DRAFT"
    line_amount_type: str = "Exclusive"


@dataclass
class QuotePayload:
    """Data needed to create a quote in any accounting system."""

    client_external_id: str
    client_name: str
    line_items: list[DocumentLineItem]
    date: date
    expiry_date: date
    currency_code: str = "NZD"
    reference: str | None = None
    status: str = "DRAFT"
    line_amount_type: str = "Exclusive"


@dataclass
class POPayload:
    """Data needed to create/update a purchase order in any accounting system."""

    supplier_external_id: str
    supplier_name: str
    po_number: str
    line_items: list[DocumentLineItem]
    date: date
    status: str = "DRAFT"
    delivery_date: date | None = None
    reference: str | None = None
    external_id: str | None = None


@dataclass
class DocumentResult:
    """Result of a document operation (create/update/delete)."""

    success: bool
    external_id: str | None = None
    number: str | None = None
    online_url: str | None = None
    raw_response: dict | None = None
    error: str | None = None
    status_code: int | None = None
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class ContactResult:
    """Result of a contact operation."""

    success: bool
    external_id: str | None = None
    name: str | None = None
    error: str | None = None
    raw_response: dict | None = None
