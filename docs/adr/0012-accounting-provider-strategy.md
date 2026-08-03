# 0012 — Accounting provider strategy with registry

All accounting access goes through `get_provider()`; SDK types never leave the provider that owns them.

## Rules

- `AccountingProvider` (a Protocol in `apps/workflow/accounting/provider.py`) covers auth, contacts, documents, and sync-pull, plus capability flags (`supports_projects`, `supports_payroll`). `get_provider()` in `registry.py` reads `settings.ACCOUNTING_BACKEND` (default `"xero"`) and returns the active instance — the only entry point business logic uses.
- Payloads cross the boundary as provider-agnostic dataclasses (`InvoicePayload`, `QuotePayload`, `POPayload`, `DocumentResult` in `types.py`). `xero_python` imports live only inside the Xero provider; a caller importing SDK types directly is a review finding.
- `xero_*` model fields keep their names; a MYOB installation leaves them null. `CompanyDefaults.accounting_provider` records the active backend.
- Some surfaces are Xero-specific deliberately and stay that way: webhooks, OAuth scopes, `XeroPayRun` models, Xero management commands.

## Do not

- **Per-provider model subclasses (`XeroInvoice`, `MyobInvoice`)** — Docketworks is single-tenant, so exactly one backend is active per installation; model-level polymorphism is dead weight at runtime.
