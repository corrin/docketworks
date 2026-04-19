# 0012 — Accounting provider strategy with registry

Introduce an `AccountingProvider` protocol with per-backend implementations (Xero today, MYOB next) resolved at request time via `get_provider()` — runtime polymorphism at the API boundary only, since each single-tenant installation has exactly one active backend.

- **Status:** Accepted (Phase 1 — interface exists; later phases in progress)
- **Date:** 2026-04-12
- **PR(s):** [#134](https://github.com/corrin/docketworks/pull/134) — fix: WIP historical state, codesight setup, env variable rename (Phase 1 bundled in; further phases land separately)

## Context

A new customer uses MYOB, not Xero. Docketworks is single-tenant (one installation per client, one accounting backend per installation — see `project_not_multitenant.md`), but the Xero integration (~6800 lines across 11 files in `apps/workflow/api/xero/`, plus document managers under `apps/workflow/views/xero/`, plus direct `xero_python` SDK usage in `client_rest_service.py`) is the only backend the code knows how to talk to. About 40% of callers import `xero_python` types directly — document managers, client service, management commands — so the SDK types leak into business logic. We need to talk to either Xero or MYOB from the same business logic, without rewriting models or schedulers.

## Decision

Strategy pattern, registry-resolved at request time: `apps/workflow/accounting/provider.py` defines `AccountingProvider` (Protocol) covering auth, contacts, documents, sync-pull, and optional capability flags (`supports_projects`, `supports_payroll`). `apps/workflow/accounting/registry.py` exposes `get_provider()`, which reads `settings.ACCOUNTING_BACKEND` (default `"xero"`) and returns the active instance. `apps/workflow/accounting/types.py` defines provider-agnostic payload dataclasses (`InvoicePayload`, `QuotePayload`, `POPayload`, `DocumentResult`) so `xero_python` types stay inside the Xero provider. Keep all existing `xero_*` model fields — they have data and migrations; MYOB installations simply leave them null. Add `CompanyDefaults.accounting_provider` to track which backend is active. Phase the rollout: (1) interface + thin Xero wrapper over existing code, (2) document managers build generic payloads, (3) client service calls `get_provider()`, (4) sync layer becomes provider-agnostic, (5) build MYOB provider.

## Alternatives considered

- **Fork the codebase per client:** maintenance nightmare for any shared fix; rejected immediately.
- **Abstract at the model layer (`Invoice` polymorphic per provider):** overengineered given the single-tenant constraint. Only one backend is ever active per installation, so runtime polymorphism at the API boundary is sufficient.
- **Rename `xero_*` fields to generic names with a data migration:** huge migration cost, breaks every query, no behaviour benefit — only one backend uses each field anyway.
- **Big-bang rewrite:** unreviewable. The phased rollout keeps existing Xero paths working through every intermediate state.

## Consequences

- **Positive:** MYOB can be added without touching business logic; `xero_python` SDK types never need to appear in views or service code once Phase 2 lands; the same sync orchestration serves both backends.
- **Negative / costs:** another layer of indirection for Xero-only reads; callers must remember to go through `get_provider()` and not import `xero_python` directly — new code needs review for this. Some things stay Xero-specific forever (webhooks, management commands, `XeroPayRun`/`XeroJournal` models, OAuth scopes) and that's deliberate.
- **Follow-ups:** Phases 2–5 still in flight; code-review round caught DRY violations and missing `persist_app_error` calls in the Phase 1 wrapper (fixed in the `accounting-provider-review-fixes` follow-up plan, now deleted — the fixes themselves are in the code and not architectural).
