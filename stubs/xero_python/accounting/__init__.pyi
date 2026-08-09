from typing import Any

from xero_python.api_client import ApiClient

class AccountType:
    value: str
    def __init__(self, **kwargs: Any) -> None: ...

class Account:
    account_id: str | None
    code: str | None
    name: str | None
    description: str | None
    type: AccountType | None
    tax_type: str | None
    enable_payments_to_account: bool | None
    _updated_date_utc: Any
    def __init__(self, **kwargs: Any) -> None: ...

class Phone:
    phone_type: str | None
    phone_number: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class Address:
    address_type: str | None
    attention_to: str | None
    address_line1: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class Contact:
    contact_id: str | None
    contact_status: str | None
    merged_to_contact_id: str | None
    name: str | None
    email_address: str | None
    phones: list[Phone] | None
    addresses: list[Address] | None
    is_customer: bool | None
    updated_date_utc: Any
    def __init__(self, **kwargs: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class Contacts:
    contacts: list[Contact] | None
    def __init__(self, contacts: list[Contact] | None = None, **kwargs: Any) -> None: ...

class LineItem:
    description: str | None
    quantity: float | None
    unit_amount: float | None
    account_code: str | None
    item_code: str | None
    line_item_id: str | None
    def __init__(self, **kwargs: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class Invoice:
    invoice_id: str | None
    invoice_number: str | None
    type: str | None
    contact: Contact | None
    date: Any
    due_date: Any
    status: str | None
    line_items: list[LineItem] | None
    sub_total: Any
    total_tax: Any
    total: Any
    amount_due: Any
    branding_theme_id: str | None
    updated_date_utc: Any
    def __init__(self, **kwargs: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class Invoices:
    invoices: list[Invoice] | None
    def __init__(self, invoices: list[Invoice] | None = None, **kwargs: Any) -> None: ...

class Quote:
    quote_id: str | None
    quote_number: str | None
    contact: Contact | None
    date: Any
    expiry_date: Any
    status: str | None
    line_items: list[LineItem] | None
    branding_theme_id: str | None
    terms: str | None
    reference: str | None
    updated_date_utc: Any
    def __init__(self, **kwargs: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class Quotes:
    quotes: list[Quote] | None
    def __init__(self, quotes: list[Quote] | None = None, **kwargs: Any) -> None: ...

class ValidationError:
    message: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class PurchaseOrder:
    purchase_order_id: str | None
    purchase_order_number: str | None
    contact: Contact | None
    date: Any
    delivery_date: Any
    status: str | None
    reference: str | None
    line_items: list[LineItem] | None
    validation_errors: list[ValidationError] | None
    updated_date_utc: Any
    def __init__(self, **kwargs: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class PurchaseOrders:
    purchase_orders: list[PurchaseOrder] | None
    def __init__(
        self, purchase_orders: list[PurchaseOrder] | None = None, **kwargs: Any
    ) -> None: ...

class HistoryRecord:
    details: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class HistoryRecords:
    history_records: list[HistoryRecord] | None
    def __init__(self, history_records: list[HistoryRecord] | None = None) -> None: ...

class BrandingTheme:
    branding_theme_id: str | None
    name: str | None
    sort_order: int | None
    def __init__(self, **kwargs: Any) -> None: ...

class BrandingThemes:
    branding_themes: list[BrandingTheme] | None
    def __init__(self, **kwargs: Any) -> None: ...

class AccountingApi:
    def __init__(self, api_client: ApiClient) -> None: ...
    def create_contacts(self, xero_tenant_id: str, contacts: Any, **kwargs: Any) -> Contacts: ...
    def update_contact(
        self, xero_tenant_id: str, contact_id: Any, contacts: Any, **kwargs: Any
    ) -> Contacts: ...
    def get_contacts(self, xero_tenant_id: str, **kwargs: Any) -> Contacts: ...
    def get_branding_themes(self, xero_tenant_id: str, **kwargs: Any) -> BrandingThemes: ...
    def get_items(self, xero_tenant_id: str, **kwargs: Any) -> Any: ...
    def get_accounts(self, xero_tenant_id: str, **kwargs: Any) -> Any: ...
    def get_invoices(self, xero_tenant_id: str, **kwargs: Any) -> Any: ...
    def get_invoice(self, xero_tenant_id: str, invoice_id: Any, **kwargs: Any) -> Any: ...
    def get_quotes(self, xero_tenant_id: str, **kwargs: Any) -> Any: ...
    def get_purchase_orders(self, xero_tenant_id: str, **kwargs: Any) -> Any: ...
    def get_credit_notes(self, xero_tenant_id: str, **kwargs: Any) -> Any: ...
    def update_item(self, xero_tenant_id: str, item_id: Any, items: Any, **kwargs: Any) -> Any: ...
    def create_items(self, xero_tenant_id: str, items: Any, **kwargs: Any) -> Any: ...
    def update_or_create_items(self, xero_tenant_id: str, items: Any, **kwargs: Any) -> Any: ...
    def create_invoices(self, xero_tenant_id: str, invoices: Any, **kwargs: Any) -> Invoices: ...
    def update_or_create_invoices(
        self, xero_tenant_id: str, invoices: Any, **kwargs: Any
    ) -> Invoices: ...
    def create_invoice_attachment_by_file_name(
        self, xero_tenant_id: str, invoice_id: Any, file_name: str, body: Any, **kwargs: Any
    ) -> Any: ...
    def create_invoice_history(
        self, xero_tenant_id: str, invoice_id: Any, history_records: Any, **kwargs: Any
    ) -> Any: ...
    def create_quote_history(
        self, xero_tenant_id: str, quote_id: Any, history_records: Any, **kwargs: Any
    ) -> Any: ...
    def get_quote(self, xero_tenant_id: str, quote_id: Any, **kwargs: Any) -> Quotes: ...
    def get_quote_as_pdf(self, xero_tenant_id: str, quote_id: Any, **kwargs: Any) -> Any: ...
    def create_quotes(self, xero_tenant_id: str, quotes: Any, **kwargs: Any) -> Quotes: ...
    def update_or_create_quotes(
        self, xero_tenant_id: str, quotes: Any, **kwargs: Any
    ) -> Quotes: ...
    def get_purchase_order(
        self, xero_tenant_id: str, purchase_order_id: Any, **kwargs: Any
    ) -> PurchaseOrders: ...
    def update_or_create_purchase_orders(
        self, xero_tenant_id: str, purchase_orders: Any, **kwargs: Any
    ) -> PurchaseOrders: ...
