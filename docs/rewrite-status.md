# Rewrite status — what is done, what remains, what needs a decision

The durable record of remaining work. Session transcripts and agent reports are
NOT durable; anything that must survive belongs here, in the parity ledger
(`accepted-api-differences.yml`), an ADR, the cutover checklist, or a code
comment at the seam itself.

**Update this file at the end of every slice**, before the PR merges.

Last updated: 2026-08-04 (frontend testing plan recorded; Phase 3c-3 quoting still current).

## Where things stand

| Measure | Value |
|---|---|
| API operations ported | **160 of 306** (parity diff, drift 0, ratcheting baseline) |
| Tests | 1028 (all passing; the 2 scraper-fill `xfail`s now pass) |
| Coverage | 88.64% (floor 85, ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, zero `type: ignore`, all gates on every commit |
| Parity ledger | 51 recorded deviations |
| ADRs | 33 (v1's 26 carried forward + 0038–0041, 0043 written here) |

Domains complete: core, accounts, company, CRM, job (core + costing +
kanban/files/PDFs), timesheets, purchasing, quoting.

2026-08-04: the whole ADR corpus was rewritten for its actual reader (an LLM
session): every rule and forcing fact kept, in plain prose; narrative
Problem/Why/Consequences and "Alternatives considered" essays removed —
a deliberation record hands a future session its rationalization, so tempting
wrong turns are now `## Do not` prohibitions with a one-line reality. Corpus
14,481 → ~7,100 words; same numbering and filenames (176 in-code citations
untouched); three-agent fidelity check against the pre-rewrite text found and
restored 13 dropped facts. New ADR 0043: comments record the rejected
alternative. Pre-rewrite text: git history (and `_template.md` defines the
format).

## Open decisions — need YOUR answer

0. **Merge PR #19, or fix Tier 1 first?** Recommendation: fix Tier 1 first —
   see "STOP HERE ON RESUME" below. Nothing in that list has been started.
   Sub-decision: whether the ADR 0040 cleanup (Tier 1 item 2) becomes its own
   PR, since it touches purchasing rather than quoting.
1. **KAN-329 in v1.** v2 is fixed and pinned (ADR 0040); v1 is still broken. One
   line in `purchasing_rest_service.py` if you want it fixed there — awaiting
   your go-ahead, since that is the production repo.

_Resolved 2026-08-03:_ the supplier-product parse defect (marker is
`parser_version`, and the operator's hand-validation always wins — both
implemented, ledgered, and covered by tests that were previously `xfail`); the
Selenium/Steel & Tube port (**required**, DONE — see below); and the 559 stale
placeholders (verified in SQL: all 559 are picked up automatically by the fixed
fill for ~6 LLM calls, and the 644 already-parsed rows are not re-processed).

## Measured risk: the sitemap shard

The scraper reads `sitemap_0.xml` only (v1 did too — inherited, not a
regression). If the catalogue ever spans a second shard, those products become
invisible AND get retired by the discontinue sweep. Measured against the
2026-08-01 restore: **3,677 distinct product URLs**, against a sitemap shard
limit of 50,000 — roughly 7% of one shard, so there is ample headroom today and
this is a monitoring concern, not a live bug. The pre-cutover live-portal run
should confirm the shard count; if a second ever appears, the discontinue sweep
must be taught about it before it runs.

## STOP HERE ON RESUME — PR #19 review, 2026-08-04

**State: PR #19 (`phase3c-3-quoting` → main) is OPEN and DELIBERATELY NOT
MERGED.** Branch pushed at `c2f3a95`, all CI green (backend, frontend,
CodeRabbit). A five-reviewer audit then found real defects. Recommendation on
the table: **fix Tier 1 before merging.** Nothing below has been started.

The findings are ranked. Tier 1 is the merge blocker list.

### Tier 1 — fix before merging

1. **A run that writes NOTHING records `completed` and retires the catalogue.**
   `ScrapeOutcome.unhealthy_reason()` (`scrapers/base.py:174`) counts *pages
   read* and never consults `refused`, though it is a field on the same
   dataclass. Verified empirically, not reasoned — probe result:
   `status='completed' products_scraped=2 rows_written=0 stale_retired=True`,
   with the run's own log saying `2 successful, 0 failed, 2 refused`. This is
   the February-2026 outage shape (a green run that achieved nothing) reached
   through a second door: the check was written for "portal redesign breaks
   every page", not "the database refuses every row".
   *Damage is currently LATENT*: `is_discontinued` has zero readers anywhere in
   `apps/` or `frontend/src` (grep-verified), so the retirement corrupts a
   column nobody queries — a landmine, not a fire. It goes live the moment
   anything reads it. Fix: `unhealthy_reason()` must fail a run whose written
   rows are zero (or refused-dominated), and reconciliation must be gated on it.
2. **ADR 0040 is applied to 1 of 4 sibling schemas, and two comments claim
   otherwise.** `NullableText` (`purchasing/schemas.py:29`, written on this
   branch) is used only by `PurchaseOrderLineCreateRequest`. Still carrying the
   `_blank_to_none` shim the ADR forbids, on the SAME five field names in the
   SAME file: `StockItemRequest:442`, `PatchedStockItemRequest:464`,
   `ProductMappingValidateRequest:595`. Plus the service-side shim
   `stock_service.py:109` (`data.get(field) or None` — which also turns a
   legitimate `Decimal("0")` into NULL for `unit_revenue`).
   Live contract split: `PATCH` a PO line with `{"specifics": ""}` → 422; the
   identical PATCH on a stock row → silently written to NULL.
   Two comments assert the opposite and are FALSE: `schemas.py:23-28` ("single
   source of truth… a new nullable field needs no service-side change") and
   `core/patching.py:8-14` ("`""` is a validation 400 before any service sees
   it" — wrong for stock and product-mapping fields, and it is 422 not 400).
   **This is v1's pathology inside the branch that wrote the rule against it:**
   a rule, a partial application, and documentation enforcing the divergence.
   Consider splitting into its own PR — it touches purchasing, not quoting.
3. **`to_optional_decimal` bounds NaN/Infinity but not MAGNITUDE.**
   `product_parser.py:149`. `parser_confidence` is `numeric(3,2)`; a model
   answering `"confidence": 95` (percent instead of 0-1 — and the prompt at
   `:272` asks for it as a *string*) raises `DataError: numeric field overflow`.
   Nothing between `_save_mapping`, `parse_products_batch` and
   `populate_all_mappings_with_llm` catches it, so one poison row kills the rest
   of its batch AND every remaining batch — up to 77 batches at 7,614 products.
   `BaseScraper._parse_new_products` then swallows it into an AppError and the
   scrape reports success. **This is the v1 "0 of 7,614 enriched" symptom
   returning.** Same exception also skips the `parser_attempted_at` write in
   `stock_parser.py:149`, so the row is re-queued forever, one wasted LLM call
   per run. Fix: bound by the column's max_digits/decimal_places, return `None`
   out of range exactly as it does for NaN.
4. **Five `persist_app_error(exc)` calls with no `AppErrorContext`** (ADR 0019):
   `stock_parser.py:152` (has `stock.id`), `purchasing/tasks.py:113` (has
   `stock_id`, `force`) and `:136`, `quoting/tasks.py:53`,
   `management/commands/run_scrapers.py:85` (has the supplier name). Because
   ADR 0001 idempotency means the INNER write wins, the surviving row is the
   context-free one — a Gemini failure on one stock row lands with a traceback
   and **no stock id at all**, unjoinable back to the row. The correct pattern
   is in this same slice: `BaseScraper._context()` (`scrapers/base.py:295`).
5. **`_hash_matches_stored_input` is entirely untested** (`product_parser.py:606`;
   coverage confirms 618-627 never execute). Replacing the call with `if True`
   leaves 127 tests green. It is the guard against a mapping whose `input_data`
   lost its text being parsed as `""`, filed under `sha256("")`, and back-flowed
   onto every blank product with **someone else's values**.

### Tier 2

- `resolve_target` (`ai/services/llm_client.py:87`): `or catalogue.all().first()`
  with no `Meta.ordering` on `AIProvider` picks an ARBITRARY provider (vendor,
  model, API key) when none is marked default. Should raise — missing config is
  an error (ADR 0015). Also duplicates `AIProvider.get_default()`, which now has
  zero callers.
- No `CELERY_RESULT_EXPIRES` set, so celery's 1-day default plus the
  auto-installed `celery.backend_cleanup` deletes the row: the weekly scrape
  reports `last_run_at: null` roughly 5 days in 7. v1 read
  `PeriodicTask.last_run_at`, which nothing deleted.
- N+1 in `list_product_mappings` (`supplier_pricing_service.py:101`,
  unpaginated) — one `Stock` query per mapping. **This branch activates it**: the
  guard was almost always false in v1 because nothing was ever enriched.
- `close_browser()` raising in the `finally` (`scrapers/base.py:491`) replaces the
  run's real outcome; a successful run ends `failed` naming the teardown.
- Anything failing after the try/except (`base.py:501-528`) leaves the job
  `running` forever — the one status nothing alerts on.
- 404-retirement path (`steel_and_tube.py:361`) calls `_mark_discontinued`
  directly, bypassing all three of `reconcile_catalogue`'s gates; it retires on
  a failed or `--limit`ed run, and is a no-op on the healthy `--refresh-old` run
  that production actually uses.
- No sanity floor on `len(published)/len(known)` before the retirement sweep —
  the missing defence for the sitemap-shard risk recorded above.

### Tier 3

- `test_price_extraction.py:59` "no vendor SDK imported" greps `f"import {sdk}"`,
  so it MISSES `from mistralai import Mistral`, `from openai import OpenAI`,
  `from google.generativeai import ...` — 3 of the 5 SDKs it names, and both of
  v1's actual import forms. Fix by AST-walking, or delete it and add a real
  import-linter contract.
- Weak/vacuous: `test_price_extraction.py:48` (asserts docstring headings),
  `test_llm_client.py:195` (constant == constant),
  `test_scheduled_tasks_api.py:96` (asserts a hardcoded `True`),
  `test_stock_metadata_tasks.py:102-155` (mocks the unit under test).
- `MAX_FAILURE_RATIO` is only pinned to somewhere in (0.6, 0.8) — the 50%
  boundary and `>` vs `>=` are untested.
- Untested: the per-row savepoint in `save_products` (Django's own
  `update_or_create` masks it; the line it really protects is
  `create_mapping_record` at `base.py:447`), `_save_mapping`'s concurrent-parse
  branch, `scheduled_task_service.py`'s malformed-entry guards.
- `_connection_hygiene` is now on its FOURTH copy (quoting/tasks.py:21,
  purchasing/tasks.py:88, job/tasks.py inlines it ×4, crm/tasks.py calls the
  unguarded form — a real bug under eager mode). One `apps/core` home is the fix.
- `to_optional_decimal` has a pre-existing sibling `_decimal_or_none`
  (`crm/services/phone_call_service.py:1017`) with NO `is_finite()` check,
  writing `Decimal("NaN")` into the call `charge` money column.
- Cosmetic: `base.py:352` fetches all known URLs then discards them when
  `refresh_old`; `scheduled_task_service.py:119` has an unreachable-false guard;
  `llm_client.py:80` truthiness-tests a `str | None`; `llm_client.py:116` sets a
  module global on every call.

### What the audit confirmed is GOOD (don't re-litigate)

Nine load-bearing behaviours were mutated in the real source; **five mutations
were killed**, including every marquee February-2026 claim (the `--limit`
retirement guard, the `unhealthy_reason` gate as far as it goes, the mid-run
`ScraperLoginError` abort, the cache-lookup fix, `_save_mapping`'s
operator-wins). The 89.8% is NOT hollow. `AUTHORITATIVE_MAPPING` was verified by
compiling the SQL — the `filter`/`exclude` sides are exact complements, and
Django's injected `IS NOT NULL` is what makes NULL-version placeholders land in
the work list. Per-row savepoints genuinely isolate a bad row. The upsert key
genuinely matches the DB constraint. ADR 0041 holds — `apps/ai` is the only
`litellm` import in the tree. No duplication at all inside `apps/quoting`.

## Review findings — Phase 3c-3 branch (2026-08-03)

Five independent reviewers over non-overlapping scopes. **[V]** = reproduced
empirically; **[R]** = traced but not independently reproduced.

### Blockers

1. ~~**[V] One blank string aborts an entire scrape.**~~ **FIXED** with the
   Selenium port. `ScrapedProduct` now refuses `""` in any of the five nullable
   text columns (unset is NULL, ADR 0040), so the failure lands inside the
   per-URL guard and costs one page; and `save_products` wraps each row in its
   own savepoint, returning the count the database refused, so one unsaveable
   variant cannot take the batch — or the transaction — with it. The count is
   recorded on the `ScrapeJob` and each refusal gets an `AppError`.
2. ~~**[V] `--limit` does not limit the discontinue sweep.**~~ **FIXED.** The
   sweep moved out of `select_urls` (which now writes nothing) into
   `reconcile_catalogue`, which refuses to run at all when `--limit` is set: a
   truncated run has not seen enough of the catalogue to retire anything.
3. ~~**[V] A run that failed every page is recorded `completed`.**~~ **FIXED.**
   `ScrapeOutcome.unhealthy_reason()` fails a run with zero successful pages, or
   with more than `MAX_FAILURE_RATIO` (50%) of pages failing, and `run()` skips
   the catalogue reconciliation entirely on such a run. Zero pages *attempted*
   (nothing new published) is still a legitimate success.
4. ~~**[V] Beat wiring: `periodic_task_name` must go under `options.headers`.**~~
   **FIXED.** `_with_periodic_task_headers` in `config/celery.py` stamps every
   entry with its own name, derived rather than written per-entry so a new
   schedule cannot forget it. Verified end to end, not assumed: the header
   survives into the published message and `Context(...).periodic_task_name`
   resolves on the worker side (eager mode skips the message layer, so the test
   dispatches through a memory broker). Removing the stamp fails three tests.
   `scheduled_task_service.py`'s docstring, which gave the wrong form, is
   corrected.
5. ~~**[V] Migration 0002's three skip paths are silent, and there is no
   `LOGGING` config.**~~ **FIXED.** The logic moved to
   `migrations/_0002_helpers.py` (a migration must not import app code, but a
   helper dedicated to one migration is as frozen as the migration) and now
   classifies every row *before* writing any: a row it cannot convert aborts,
   naming the primary keys, and nothing is written at all. The old message
   claimed N rows were converted "before this point", which `RunPython`'s
   transaction would have rolled back — a lie of exactly the kind this pass is
   removing. `LOGGING` is now configured in `config/settings.py`; without it
   Django discards app loggers entirely unless `DEBUG`, so every `logger.warning`
   in a service, task or migration went nowhere in production.
   `exclude(input_data=None)` was dead code — the column is `NOT NULL`.

### Major

- ~~**[V] Upsert key ≠ enforced uniqueness key.**~~ **FIXED:** `save_products`
  now keys `update_or_create` on the full `unique_together`
  (`supplier, url, item_no, variant_id`). The database is the authority; a
  product that moves URL becomes a new row and the row at the old URL is retired
  by `reconcile_catalogue` when that URL leaves the sitemap, which is what "the
  product moved" means to us. (Tightening the constraint instead would have
  needed a migration, and v2.0 migrates data by pg_dump/restore.)
- ~~**[V] `to_optional_decimal` admits NaN/Infinity.**~~ **FIXED:** non-finite
  values are `None`, including via the `Decimal` fast path.
- **[R] No timeout, retry or spend cap at the LLM boundary.** litellm's default
  `request_timeout` is 6000s, so a hung vendor pins a worker for 100 minutes.
  ADR 0041 claims the gateway is where these live; make that true.
- **[R] Six unrecorded API deviations**, incl. `render_schedule` strings
  (`5.00 minutes` vs v1's `every 5 minutes`, missing timezone suffix) and search
  not implementing DRF's token splitting (`?search=entry apps.job` → v1 120
  rows, v2 **0**).
- ~~**[R] All six `persist_app_error` calls pass no `AppErrorContext`.**~~
  **FIXED in the scrapers** (`BaseScraper._context`): every persisted scraper
  failure now carries supplier, `scrape_job_id`, phase, and the URL/item that
  failed. The other callers in the codebase still pass nothing.

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

Done in the scraper files: `ScrapeJob`'s docstring now says it prevents nothing;
`close_browser` genuinely is always called (the `finally` moved to wrap
`open_browser`, and a half-started driver still gets its profile removed), with a
test; `is_discontinued` carries a WRITE-ONLY comment naming every place that
would have to read it — its `help_text` still lies, because editing `help_text`
is a migration and v2.0 migrates by pg_dump/restore, so **either make the flag
mean something or drop it before cutover.** The beat-wiring and litellm-stub
claims are untouched (not this slice's files).

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
| Frontend | the full SPA rebuild (React/TanStack); only login + a kanban placeholder exist | Playwright suite ports here. **Binding approach: [`frontend-testing-plan.md`](frontend-testing-plan.md)** — field manifests + diff-only PATCH builder + round-trip component tests; E2E shrinks to a smoke layer. Its Phase A (schema.v2.yml export, `src/lib/forms/`, vitest dom project) runs first, before any feature ports. Also defuses two live landmines: generated zod defaults on update schemas, and `frontend/schema.yml` being v1's frozen baseline (client cannot see v2 drift). |

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
  error). The browser layer is no longer deferred: `SeleniumScraper` (v1's
  20-flag headless Chrome, in `scrapers/base.py`) and `SteelAndTubeScraper` are
  ported and tested against a fake WebDriver. What CANNOT be tested here is
  whether the selectors still match the live portal — see the stale-selector
  list in `scrapers/steel_and_tube.py`, and **run
  `manage.py run_scrapers --supplier "Steel & Tube" --limit 2` against
  production credentials before cutover.**
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
4. `config/celery.py` entries need
   `"options": {"headers": {"periodic_task_name": "<entry>"}}` (the headers form
   — celery drops unknown top-level option keys) or the
   scheduled-task-executions endpoint and `last_run_at` stay empty. No entry
   wires it today, `run_all_scrapers_weekly` included.
5. ~~Beat entry for `run_all_scrapers_task`.~~ DONE: `run_all_scrapers_weekly`,
   `crontab(minute="0", hour="15", day_of_week="0")`, NZT via `CELERY_TIMEZONE`
   — v1's workflow/0003 seed exactly.
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
