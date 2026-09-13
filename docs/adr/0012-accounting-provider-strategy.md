# 0012 — All accounting access goes through get_provider(); SDK types never leave their provider

All accounting access goes through `get_provider()`; SDK types never leave the provider that owns them.

## Rules

- `AccountingProvider` (a Protocol in `apps/accounting/provider.py`) covers auth, contacts, documents, and sync-pull, plus the `supports_payroll` capability flag. `get_provider()` in `apps/accounting/registry.py` resolves the active backend from `CompanyDefaults.accounting_provider` and returns its instance — the only entry point business logic uses.
- Payloads cross the boundary as provider-agnostic dataclasses (`InvoicePayload`, `QuotePayload`, `POPayload`, `DocumentResult` in `types.py`). `xero_python` imports live only inside the Xero provider; a caller importing SDK types directly is a review finding.
- `xero_*` model fields keep their names; a MYOB installation leaves them null. `CompanyDefaults.accounting_provider` records the active backend — a business selector, which is why it lives there and credentials do not (ADR 0053).
- Some surfaces are Xero-specific deliberately and stay that way: webhooks, OAuth scopes, `XeroPayRun` models, Xero management commands.

## Do not

- **Per-provider model subclasses (`XeroInvoice`, `MyobInvoice`)** — Docketworks is single-tenant, so exactly one backend is active per installation; model-level polymorphism is dead weight at runtime.
