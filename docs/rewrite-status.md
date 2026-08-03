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

## Open decisions — need YOUR answer

1. **KAN-329 in v1.** v2 is fixed and pinned (ADR 0040); v1 is still broken. One
   line in `purchasing_rest_service.py` if you want it fixed there — awaiting
   your go-ahead, since that is the production repo.

_Resolved 2026-08-03:_ the supplier-product parse defect (marker is
`parser_version`, and the operator's hand-validation always wins — both
implemented, ledgered, and covered by tests that were previously `xfail`); the
Selenium/Steel & Tube port (**required**, in progress); and the 559 stale
placeholders (verified in SQL: all 559 are picked up automatically by the fixed
fill for ~6 LLM calls, and the 644 already-parsed rows are not re-processed).

## Review findings — Phase 3c-3 branch (2026-08-03)

Five independent reviewers over non-overlapping scopes. **[V]** = reproduced
empirically; **[R]** = traced but not independently reproduced.

### Blockers

1. **[V] One blank string aborts an entire scrape.** v1 wrapped each product in
   try/except; the port dropped it while adding 12 not-blank CHECKs v1 lacked,
   and `save_products` sits outside the per-URL try. A `description=""` — what
   `element.text` yields on a missing DOM cell — fails the run with 1 of 2
   products saved. *Assigned to the Selenium agent (same file).*
2. **[V] `--limit` does not limit the discontinue sweep.** `--limit 2
   --refresh-old` against a truncated sitemap retired 9 of 10 products, then
   scraped 1 URL. Docstring calls it "a testing throttle". *Assigned.*
3. **[V] A run that failed every page is recorded `completed`.** 5/5 failures →
   `status='completed'`. On the real catalogue a DOM change gives a green weekly
   run that has already retired the inventory — the same silence-looks-like-
   success shape as the Feb outage. *Assigned.*
4. **[R] Beat wiring: `periodic_task_name` must go under `options.headers`.**
   Celery drops unknown keys from its fixed header list; `django_celery_beat`
   uses the headers form. `config/celery.py` currently wires none, so
   `last_run_at` and the scheduled-task-executions endpoint are permanently
   empty — 2 of the 4 quoting endpoints return nothing in production. The advice
   in `scheduled_task_service.py`'s docstring is wrong and must be corrected.
5. **[R] Migration 0002's three skip paths are silent, and there is no `LOGGING`
   config**, so the record of what a one-shot rewrite of 1,203 production rows
   did is discarded. Two of three skips log nothing at all.

### Major

- **[V] Upsert key ≠ enforced uniqueness key** (`supplier, item_no, variant_id`
  vs `unique_together(supplier, url, item_no, variant_id)`): the DB permits
  duplicates on the app's key, and one duplicate then kills that supplier's run
  permanently with `MultipleObjectsReturned`. *Assigned.*
- **[V] `to_optional_decimal` admits NaN/Infinity** into `numeric(10,2)`,
  poisoning downstream comparisons. *Assigned.*
- **[R] No timeout, retry or spend cap at the LLM boundary.** litellm's default
  `request_timeout` is 6000s, so a hung vendor pins a worker for 100 minutes.
  ADR 0041 claims the gateway is where these live; make that true.
- **[R] Six unrecorded API deviations**, incl. `render_schedule` strings
  (`5.00 minutes` vs v1's `every 5 minutes`, missing timezone suffix) and search
  not implementing DRF's token splitting (`?search=entry apps.job` → v1 120
  rows, v2 **0**).
- **[R] All six `persist_app_error` calls pass no `AppErrorContext`** — handlers
  that exist to add context and add none. `base.py:277` knows which URL failed.

### Test-quality debt (self-reported by the author agent)

- `test_products_are_saved_in_batches_during_a_long_run` is **vacuous**:
  deleting the mid-loop flush leaves it green.
- `test_a_mapping_with_no_item_code_is_simply_not_in_xero` is tautological.
- `test_price_extraction.py` asserts docstring headings — a direct ADR 0025
  violation ("never assert the implementation's own text").
- `LLM_BOUNDARY` is module-bound: a second consumer of `chat_completion` will
  silently patch nothing. **There is no root `conftest.py` guard against a real
  network call in tests.**

### Systemic finding — treat as ONE work item

Three reviewers independently found **docstrings asserting behaviour the code
does not implement**: `ScrapeJob` "prevents concurrent runs" (nothing checks),
`close_browser` "always called" (not if `open_browser` raises), `is_discontinued`
"skips future scrapes" (no reader), the beat-wiring advice above, the litellm
stub's justification. In a codebase whose defence against duplication is
docstrings telling the next session what already exists, **prose that lies is
the highest-leverage defect class.** Sweep: make every claim true or delete it.

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
7. Root `conftest.py` guard that fails any test attempting a real network call
   (the LLM boundary is currently protected only by module-bound patching).
8. Add `LOGGING` config — there is none, so `logger.info/warning` from
   migrations, tasks and services reaches no handler.
9. Rewrite the three known-weak tests listed under Test-quality debt rather
   than leaving green-but-meaningless assertions in place.

## v1 defects found by this rewrite

Recorded because they are live in production, not just porting notes. Full
detail in the parity ledger.

- **KAN-329** — blank `item_code` on a PO line trips its own CHECK constraint
  (409, price change rolled back). Unfixed in v1.
- **Supplier-product parse** — the end-of-run LLM fill never ran: 559 of 1,203
  mappings never parsed, 0 of 7,614 products enriched, across 8 months of
  weekly scrapes. Two independent causes, both ported verbatim from v1 and both
  fixed in v2 on 2026-08-03 (see the parity ledger). Still broken in v1.
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
