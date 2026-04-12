# Accounting Provider Abstraction

## Context

A customer uses MYOB instead of Xero. Docketworks is single-tenant (one installation per client), so each instance uses exactly one accounting package. We need an abstraction layer so the business logic stays the same regardless of which accounting backend is active.

The current Xero integration is ~6800 lines across 11 files in `apps/workflow/api/xero/`, plus document managers in `apps/workflow/views/xero/`, plus direct `xero_python` SDK usage in `client_rest_service.py`. About 60% of callers already go through an API function layer (well decoupled); 40% import `xero_python` types directly (document managers, client service, management commands).

## Design

### Pattern: Provider Strategy with Registry

Since each installation uses ONE accounting package, we need runtime polymorphism at the **API boundary** only — where code talks to external systems. Not at the model layer.

```
Business Logic (sync service, views, schedulers)
    |
    v
AccountingProvider Protocol (new interface)
    |
    v
XeroProvider / MYOBProvider (implementation per backend)
```

### New Package Structure

```
apps/workflow/accounting/
    __init__.py
    provider.py          # Protocol definition
    registry.py          # get_provider() → returns the active backend
    types.py             # Provider-agnostic dataclasses (InvoicePayload, DocumentResult, etc.)
    xero/
        __init__.py
        provider.py      # XeroAccountingProvider — delegates to existing api/xero/ code
    myob/                # Future
        __init__.py
        provider.py
```

### The Protocol (`apps/workflow/accounting/provider.py`)

```python
class AccountingProvider(Protocol):
    # --- Auth ---
    def get_auth_url(self, state: str) -> str: ...
    def exchange_code(self, code: str, state: str, session_state: str) -> dict: ...
    def get_valid_token(self) -> dict | None: ...
    def refresh_token(self) -> dict | None: ...
    def disconnect(self) -> None: ...

    # --- Contacts ---
    def create_contact(self, contact_data: dict) -> str: ...  # returns external ID
    def update_contact(self, external_id: str, contact_data: dict) -> None: ...
    def search_contact_by_name(self, name: str) -> dict | None: ...
    def fetch_contacts(self, since: datetime | None, **kwargs) -> list: ...

    # --- Documents ---
    def create_invoice(self, payload: InvoicePayload) -> DocumentResult: ...
    def delete_invoice(self, external_id: str) -> DocumentResult: ...
    def create_quote(self, payload: QuotePayload) -> DocumentResult: ...
    def delete_quote(self, external_id: str) -> DocumentResult: ...
    def create_purchase_order(self, payload: POPayload) -> DocumentResult: ...
    def delete_purchase_order(self, external_id: str) -> DocumentResult: ...

    # --- Sync (Pull) ---
    def fetch_invoices(self, since: datetime | None, **kwargs) -> list[dict]: ...
    def fetch_bills(self, since: datetime | None, **kwargs) -> list[dict]: ...
    def fetch_accounts(self, since: datetime | None, **kwargs) -> list[dict]: ...
    def fetch_stock(self, since: datetime | None, **kwargs) -> list[dict]: ...
    # ... other entity types

    # --- Optional capabilities ---
    @property
    def supports_projects(self) -> bool: ...
    @property
    def supports_payroll(self) -> bool: ...

    # --- Projects (Xero has this, MYOB doesn't) ---
    def push_job_as_project(self, job) -> bool: ...
    def sync_costlines_to_project(self, job) -> bool: ...

    # --- Stock ---
    def push_stock_item(self, stock) -> str: ...  # returns external ID
    def fetch_all_stock_items(self) -> list[dict]: ...
```

### The Registry (`apps/workflow/accounting/registry.py`)

```python
def get_provider() -> AccountingProvider:
    backend = settings.ACCOUNTING_BACKEND  # "xero" or "myob"
    if backend not in _providers:
        raise RuntimeError(f"Unknown accounting backend '{backend}'")
    return _providers[backend]()
```

`settings.ACCOUNTING_BACKEND` defaults to `"xero"` — existing installations unchanged.

### Data Transfer Types (`apps/workflow/accounting/types.py`)

Provider-agnostic dataclasses replace direct use of `xero_python.accounting.models`:

```python
@dataclass
class DocumentLineItem:
    description: str
    quantity: Decimal
    unit_amount: Decimal
    account_code: str

@dataclass
class InvoicePayload:
    client_external_id: str
    client_name: str
    line_items: list[DocumentLineItem]
    reference: str | None
    date: date
    due_date: date

@dataclass
class DocumentResult:
    success: bool
    external_id: str | None
    number: str | None
    error: str | None
```

### Model Fields Strategy

**Keep all existing `xero_*` fields unchanged.** They work, they have data, they have migrations.

Add to `CompanyDefaults`:
- `accounting_provider` (CharField, default="xero") — which backend is active

The Xero provider reads/writes `xero_*` fields. A future MYOB provider would use `raw_json` plus any `myob_*` fields added later. Since only one provider is active per installation, there's no conflict — MYOB installations leave `xero_*` fields null.

Provider-specific models (`XeroToken`, `XeroAccount`, `XeroPayRun`, etc.) stay as-is. MYOB gets its own models when built. `XeroSyncCursor` is already structurally generic (entity_key + timestamp) — rename it to `SyncCursor` when convenient.

### Document Manager Refactoring

Current flow (tightly coupled):
```
View → XeroInvoiceManager → builds xero_python.Invoice → calls AccountingApi directly
```

New flow:
```
View → DocumentManager → builds InvoicePayload (generic dataclass) → calls get_provider().create_invoice()
    → XeroProvider builds xero_python.Invoice internally → calls AccountingApi → returns DocumentResult
```

The `xero_python` SDK types never leave the provider implementation.

## Phased Implementation

### Phase 1: Define the Interface (no behaviour changes)

Create `apps/workflow/accounting/` with `provider.py`, `registry.py`, `types.py`. Create `apps/workflow/accounting/xero/provider.py` as a thin wrapper that delegates to existing `apps/workflow/api/xero/` code. Add `ACCOUNTING_BACKEND = "xero"` to settings, `accounting_provider` field to `CompanyDefaults`.

**Result**: The interface exists, all existing code paths unchanged.

### Phase 2: Refactor Document Managers

Extract `InvoicePayload`, `QuotePayload`, `POPayload` dataclasses. Refactor `XeroDocumentManager` and subclasses to build generic payloads and call `get_provider().create_invoice()` etc. Move `xero_python` type construction into `XeroProvider`. Remove `from xero_python` imports from the view layer.

**Critical files**:
- `apps/workflow/views/xero/xero_base_manager.py` — currently imports `AccountingApi`, `Contact`, `HistoryRecord` directly
- `apps/workflow/views/xero/xero_invoice_manager.py` — imports `XeroInvoice`, `LineItem`
- `apps/workflow/views/xero/xero_quote_manager.py` — imports `XeroQuote`, `LineItem`
- `apps/workflow/views/xero/xero_po_manager.py` — imports `XeroPurchaseOrder`, `LineItem`

### Phase 3: Refactor Client REST Service

Remove `from xero_python.accounting import AccountingApi` from `apps/client/services/client_rest_service.py`. Replace direct `AccountingApi(api_client).create_contacts(...)` with `get_provider().create_contact(...)`.

**Critical file**: `apps/client/services/client_rest_service.py` (~lines 620-710)

### Phase 4: Refactor Sync Layer

Make `sync_all_xero_data()` provider-agnostic. Move `ENTITY_CONFIGS` into the provider — each provider defines which entities it syncs and how. The sync orchestrator calls `provider.fetch_invoices(since=cursor)` instead of knowing about `AccountingApi.get_invoices`.

**Critical files**:
- `apps/workflow/api/xero/sync.py` — `ENTITY_CONFIGS`, `sync_all_xero_data()`
- `apps/workflow/services/xero_sync_service.py` — rename to `accounting_sync_service.py`
- `apps/workflow/api/xero/transforms.py` — moves inside Xero provider

### Phase 5: Build MYOB Backend

Create `apps/workflow/accounting/myob/` with auth, API client, and provider implementation. Map MYOB API entities to the same `AccountingProvider` protocol. Add MYOB-specific models and env vars.

## What Stays Xero-Specific (never abstracted)

- `apps/workflow/api/xero/client.py` — SDK-specific rate limiting
- `apps/workflow/api/xero/constants.py` — OAuth scopes
- `apps/workflow/api/xero/auth.py` — `api_client` singleton, token storage
- `apps/workflow/xero_webhooks.py` — MYOB has different webhook model
- Management commands `xero.py`, `seed_xero_from_database.py` — Xero tooling
- `XeroPayRun`, `XeroPaySlip`, `XeroPayItem`, `XeroJournal` models — structurally Xero-specific
- Demo/dev scripts

## What Stays the Same for Both Providers

- Sync orchestration logic (fetch since cursor, transform, save)
- Document management flow (validate → build payload → call provider → save result)
- Client create/update flow (validate → call provider → store external ID)
- Scheduler jobs (call sync service on schedule)
- All Django models, views, templates, frontend code

## Features Xero Has That MYOB Doesn't

- **Projects API**: Controlled by `supports_projects` property. MYOB returns `False`, callers skip project sync.
- **Payroll NZ**: Controlled by `supports_payroll`. MYOB has its own payroll API with different structure — gets its own implementation if needed.

## Verification

- All existing Xero integration tests pass unchanged after Phase 1
- Document creation (invoice, quote, PO) works end-to-end after Phase 2
- Client create/update syncs to Xero after Phase 3
- Full sync completes after Phase 4
- MYOB auth + basic contact sync works after Phase 5
