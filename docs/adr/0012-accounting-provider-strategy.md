# 0012 — Accounting provider strategy with registry

`AccountingProvider` is a Protocol; per-backend implementations (Xero today, MYOB next) are resolved at request time via `get_provider()`. Runtime polymorphism at the API boundary only.

## Problem

A new customer uses MYOB, not Xero. Docketworks is single-tenant — one installation per client, one accounting backend per installation — but ~6800 lines of Xero code across 11 files in `apps/workflow/api/xero/` is the only backend the codebase knows how to talk to. About 40% of callers (document managers, client service, management commands) import `xero_python` types directly, so SDK types leak into business logic. We need to talk to either Xero or MYOB from the same business logic without rewriting models or schedulers.

## Decision

- `apps/workflow/accounting/provider.py` defines `AccountingProvider` (Protocol) covering auth, contacts, documents, sync-pull, plus capability flags (`supports_projects`, `supports_payroll`).
- `apps/workflow/accounting/registry.py` exposes `get_provider()`, which reads `settings.ACCOUNTING_BACKEND` (default `"xero"`) and returns the active instance.
- `apps/workflow/accounting/types.py` defines provider-agnostic payload dataclasses (`InvoicePayload`, `QuotePayload`, `POPayload`, `DocumentResult`).
- Existing `xero_*` model fields stay; MYOB installations leave them null. `CompanyDefaults.accounting_provider` records the active backend.

Phased rollout: (1) interface + thin Xero wrapper; (2) document managers build generic payloads; (3) client service calls `get_provider()`; (4) sync layer becomes provider-agnostic; (5) build MYOB provider.

## Why

Each installation has exactly one active backend, so a runtime-resolved registry is sufficient — model-level polymorphism (`Invoice` per provider) would be overengineered. The Protocol keeps SDK types (`xero_python.*`) out of views and services; new code can be reviewed by checking that `get_provider()` is the only entry point. Phased rollout means existing Xero paths keep working through every intermediate state; a big-bang rewrite would be unreviewable.

## Alternatives considered

- **Polymorphic models — `XeroInvoice`, `MyobInvoice` subclasses of `Invoice`.** Defendable in a multi-tenant system where one process serves multiple backends. Rejected: single-tenant constraint means only one backend is ever active per installation, so model-level polymorphism is dead weight at runtime.
- **Rename `xero_*` model fields to generic names with a data migration.** Defendable as part of a thorough rebrand. Rejected: huge migration cost; only one backend uses each field per installation anyway, so the field name doesn't actually create a problem.

## Consequences

MYOB can be added without touching business logic; SDK types stay inside the Xero provider once Phase 2 lands. Cost: another layer of indirection for Xero-only reads; new code needs review to ensure callers don't import `xero_python` directly. Some surfaces stay Xero-specific forever (webhooks, management commands, `XeroPayRun`/`XeroJournal` models, OAuth scopes) — that's deliberate.
