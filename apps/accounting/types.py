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
