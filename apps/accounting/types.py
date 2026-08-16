"""Provider-agnostic data transfer types for the accounting abstraction layer.

Grown per-slice with the AccountingProvider Protocol (ADR 0012).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

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


# --- Payroll employees -------------------------------------------------------


@dataclass(frozen=True)
class PayrollEmployeeRef:
    """A payroll employee as the matcher and the linker need to see one.

    ``job_title`` is carried because it is where the Staff UUID is stored, and
    that UUID is the only match key that survives a database restore intact.
    """

    external_id: str
    first_name: str
    last_name: str
    email: str | None
    job_title: str | None


@dataclass(frozen=True)
class PayrollAddress:
    """The employer address a payroll employee is registered against."""

    address_line1: str
    address_line2: str | None
    suburb: str | None
    city: str
    post_code: str
    country_name: str


@dataclass(frozen=True)
class NewPayrollEmployee:
    """Everything a provider needs to create one payroll employee.

    Deliberately free of provider identifiers. v1 made the caller look up the
    payroll-calendar id and the ordinary-earnings-rate id and pass them in a
    dict, which put Xero UUIDs in the domain layer; the provider resolves both
    itself from configuration it already owns.

    ``hours_per_week`` is keyed by lowercase weekday name, monday..sunday, and
    every day must be present — a partial pattern is a data defect, not a
    provider concern.
    """

    staff_id: UUID
    first_name: str
    last_name: str
    email: str
    job_title: str
    date_of_birth: "datetime.date"
    start_date: "datetime.date"
    end_date: "datetime.date | None"
    address: PayrollAddress
    hours_per_week: dict[str, float]
    hourly_rate: Decimal
    ird_number: str
    bank_account_number: str
