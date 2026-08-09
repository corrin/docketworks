"""Provider-agnostic data transfer types for the accounting abstraction layer.

Grown per-slice with the AccountingProvider Protocol (ADR 0012).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import datetime


@dataclass(frozen=True)
class DocumentTheme:
    """A selectable document presentation theme from an accounting provider."""

    external_id: str
    name: str
    is_default: bool


@dataclass(frozen=True)
class ContactResult:
    """Result of a contact operation."""

    success: bool
    external_id: str | None = None
    name: str | None = None
    error: str | None = None


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
    company_name: str
    line_items: list[DocumentLineItem]
    date: "datetime.date"
    due_date: "datetime.date"
    document_theme_external_id: str
    currency_code: str = "NZD"
    reference: str | None = None
    url: str | None = None
    status: str = "DRAFT"
    line_amount_type: str = "Exclusive"


@dataclass
class QuotePayload:
    """Data needed to create a quote in any accounting system.

    ``terms`` is required, not defaulted: Xero does not apply its own quote
    terms default to API-created quotes, so an empty value here would ship a
    quote with no terms — the manager validates before building this.
    """

    client_external_id: str
    company_name: str
    line_items: list[DocumentLineItem]
    date: "datetime.date"
    expiry_date: "datetime.date"
    document_theme_external_id: str
    terms: str
    currency_code: str = "NZD"
    reference: str | None = None
    status: str = "DRAFT"
    line_amount_type: str = "Exclusive"


@dataclass(frozen=True)
class QuotePdfDocument:
    """A provider-rendered quote PDF on local disk. The caller owns the file."""

    external_id: str
    document_theme_external_id: str | None
    temporary_file_path: str


@dataclass
class POPayload:
    """Data needed to create/update a purchase order in any accounting system."""

    supplier_external_id: str
    supplier_name: str
    po_number: str
    line_items: list[DocumentLineItem]
    date: "datetime.date"
    status: str = "DRAFT"
    delivery_date: "datetime.date | None" = None
    reference: str | None = None
    external_id: str | None = None


@dataclass
class DocumentResult:
    """Result of a document operation (create/update/delete)."""

    success: bool
    external_id: str | None = None
    number: str | None = None
    online_url: str | None = None
    raw_response: dict[str, Any] | None = None
    error: str | None = None
    status_code: int | None = None
    validation_errors: list[str] = field(default_factory=list)
