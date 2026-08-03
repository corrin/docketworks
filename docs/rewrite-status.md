# Rewrite status — what is done, what remains, what needs a decision

The durable record of remaining work. Session transcripts and agent reports are
NOT durable; anything that must survive belongs here, in the parity ledger
(`accepted-api-differences.yml`), an ADR, the cutover checklist, or a code
comment at the seam itself.

**Update this file at the end of every slice**, before the PR merges.

Last updated: 2026-08-03 (end of Phase 3c-3, quoting).

## Where things stand

| Measure | Value |
|---|---|
| API operations ported | **160 of 306** (parity diff, drift 0, ratcheting baseline) |
| Tests | 959 (957 passed, 2 xfail) |
| Coverage | 89.58% (floor 85, ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, zero `type: ignore`, all gates on every commit |
| Parity ledger | 51 recorded deviations |
| ADRs | 32 (v1's 26 carried forward + 0038–0041 written here) |

Domains complete: core, accounts, company, CRM, job (core + costing +
kanban/files/PDFs), timesheets, purchasing, quoting.

## Open decisions — these block nothing today but need YOUR answer

1. **Supplier-product parse defect (live in production).** v1's end-of-run fill
   never populates scraper-created mappings: the empty placeholder answers its
   own cache lookup, and `_save_mapping`'s `get_or_create` then discards the
   model's answer. Evidence from the restore: 559 of 1,203 mappings never
   parsed (exactly the scraper-written shape), and **0 of 7,614 supplier
   products carry parsed data** — 8 months of weekly scraping produced nothing.
   The fix must decide (a) which column means "the parser has run"
   (`parser_version` is honest; v1's `mapped_item_code__isnull` re-parses
   forever any product with no item code), and (b) whether a fill may overwrite
   a mapping an operator hand-validated. Held as two `xfail(strict=True)` tests
   in `apps/quoting/tests/test_scrapers.py::TestScraperEndOfRunFillIsBroken`,
   which flip to passing the moment it is fixed.
2. ~~**Selenium / Steel & Tube scraper.**~~ **RESOLVED 2026-08-03: the app
   requires scraping — port it.** The Feb 2026 outage was operational, not a
   code fault: the portal password changed and production was never updated.
   So this is a CUTOVER BLOCKER, not a cleanup. Port `steel_and_tube.py` and
   the browser layer; add `selenium` to pyproject. `base.py` is already ported,
   browser-free and at 100% coverage, so the remaining work is the driver
   lifecycle plus the site's selectors.

3. **559 stale placeholder mappings** in the restore: leave for the fixed fill
   to pick up, or clear at cutover.
4. **KAN-329 in v1.** v2 is fixed and pinned (ADR 0040); v1 is still broken. One
   line in `purchasing_rest_service.py` if you want it fixed there — awaiting
   your go-ahead, since that is the production repo.

## Remaining backend slices

| Slice | Scope | Notes |
|---|---|---|
| accounting / reports | invoices, bills, credit notes, KPI, WIP, sales pipeline, job aging, staff performance, month-end REST | ~13 ops under `/api/accounting`; the biggest remaining domain |
| process / safety docs | forms, form entries, procedures, JSA/SWP | ~29 ops |
| job chat + MCP | `chat_service`, `mcp_chat_service`, `quote_mode_controller` — all consume the ONE gateway (ADR 0041) | v2 has the `JobQuoteChat` model only |
| quote-to-PO | v1 `purchasing/quote_to_po_service.py`, incl. its inline Gemini client → gateway | |
| search + diagnostics + admin | telemetry writes (deferred from company/kanban/stock search), session replay, app-errors, scheduled tasks, AI providers | |
| **Phase 4: Xero** | sync, push, webhooks, payroll, OAuth callback | Largest remaining risk. Your last free ultrareview is earmarked here. Exact-URL parity required. |
| Phase 5: ops | AccessLogging/DisallowedHost/FrontendRedirect/PasswordStrength middlewares, Dropbox API sync, deploy scripts | |
| Frontend | the full SPA rebuild (React/TanStack); only login + a kanban placeholder exist | Playwright suite ports here |

## Deferrals carried inside completed slices

Each has a loud seam in code (`grep -rn "Phase 4\|Phase 5\|SEAM" apps/`); listed
so they are not rediscovered by accident.

- **Xero (Phase 4):** company create / Xero-synced company update; PO push/delete
  (lives on the `/api/xero/` surface); payroll pay-run create/refresh/calendar
  anchor; employee sync (the matching engine underneath IS ported and tested);
  `Company.get_company_for_xero`.
- **Search telemetry:** company search, kanban search and stock search all emit
  the structured log line but write no `SearchTelemetryEvent` (layer contract) —
  returns with the search slice.
- **Quoting:** PDF price-list extraction (`extract_price_data` raises a named
  error); browser layer as above.
- **Job:** month-end REST screens; `update_completion_checklist`; weekly-metrics;
  invoices/quote GET endpoints; quote apply/link/preview (Google Sheets sync).
- **Purchasing:** re-receipting a line deletes prior stock but keeps
  accumulating `received_quantity` — ported v1 debt, ledgered, needs a
  deliberate stock-reconciliation decision.
- **Timesheet:** `/api/job/timesheet/*` modern-timesheet endpoints (4 ops);
  `demo_payroll_data` (needs `python-stdnum`); `xero_hours` + 5 data-repair
  management commands.

## Engineering backlog (no decision needed, just work)

1. Port v1's kanban search-ranking test net (~30 tests). The scoring code is
   line-identical to v1 but the regression net is thin (4 tests).
2. CRM wire-pin tests (portal login/CDR form fields, `b"200"` strip,
   `Result == "1"`, timeouts) and superuser-gate tests on recording deletes and
   endpoint CRUD.
3. Hoist connection hygiene (`close_old_connections` guarded by
   `in_atomic_block`) into `apps/core`: four copies exist and
   `apps/crm/tasks.py` still has two unguarded calls.
4. `config/celery.py` entries need `"options": {"periodic_task_name": "<entry>"}`
   or the scheduled-task-executions endpoint and `last_run_at` stay empty.
5. Beat entry for `run_all_scrapers_task` (Sunday 15:00 NZT) when the scrapers
   land; month-end job beat entries are already restored.
6. Test suite is ~6 min serial on 16 cores — parallelise with `pytest-xdist`
   (`--dist loadscope` for the DB fixtures).

## v1 defects found by this rewrite

Recorded because they are live in production, not just porting notes. Full
detail in the parity ledger.

- **KAN-329** — blank `item_code` on a PO line trips its own CHECK constraint
  (409, price change rolled back). Unfixed in v1.
- **Supplier-product parse** — open decision 1 above; 0 of 7,614 products
  enriched.
- **`consume_stock`** silently lost a changed quantity (omitted from
  `update_fields`).
- **PO email** `recipient_email` was completely inert; `email_body` and
  `mailto_url` disagreed.
- **Company merge** dropped a primary-contact flag when the source primary
  duplicated a destination row.
- **Departed staff could log in**, then 401 on every request (silent redirect
  loop).
- **Workshop timesheets accepted negative hours** into job costing.
- **Time pricing** silently substituted the company default wage rate, or
  costed labour at $0.00.
- **Migration tooling:** the sequence reset matched zero of 20 sequences
  (Django 6 identity columns), so the first insert after any production load
  would have failed. Fixed and now verified by the script itself.
