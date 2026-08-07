# Rewrite status — what is done, what remains, what needs a decision

The durable record of remaining work. Session transcripts and agent reports are
NOT durable; anything that must survive belongs here, in the parity ledger
(`accepted-api-differences.yml`), an ADR, the cutover checklist, or a code
comment at the seam itself.

**What belongs here: work not yet done, decisions not yet made, and constraints
that would otherwise be re-broken.** Not a changelog. If a line only records
that something was fixed, delete it — git holds that, and a reader hunting for
what to do next has to wade through it. The test for any line: *does this change
what the next session does?*

**Update this file at the end of every slice**, before the PR merges.

Last updated: 2026-08-06 NZ (seed/restore collision fixed and the load
rehearsed clean; resolved findings retired — see the inclusion rule above).

## Where things stand

| Measure | Value |
|---|---|
| API operations ported | **175 of 306** (parity diff, drift 0, ratcheting baseline) |
| Tests | 1274 (all passing) |
| Coverage | 91.12% (floor 88, ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, zero `type: ignore`, all gates on every commit |
| Contract gaps vs v1 | **152**, ratcheting to zero (`scripts/schema-contract-gaps.txt`, ADR 0044). `uuid` at zero; `nullable` 146, `required` 6 |
| Parity ledger | 69 recorded deviations |
| ADRs | 33 (v1's 26 carried forward + 0038–0041, 0043–0045 written here) |

The standing gates are ruff, mypy (strict, zero baseline), import-linter,
makemigrations --check, deptry, **find-duplicates** and the frontend trio, all
on pre-commit; CI adds the parity diff and the exported-schema freshness check.
`find_duplicates.py` catches the two shapes a linter cannot see, because they
are properties of the tree rather than of a file: sibling modules
(`job_rest_service.py` beside `job_service.py`, which is how v1 rotted) and a
public symbol defined in two modules. It was verified against v1 rather than
assumed: run over v1 the sibling check reports four pairs —
`job_rest_service`/`job_service`, and `urls_rest`/`urls` in each of job,
process and purchasing. The symbol check does **not** catch those — measured,
six hits in v1, none of them the parallel job services — so do not rely on it
for differently-named copies. It deliberately does **not** scan within a file
for duplicate methods, attributes or dict keys: ruff's F811, PIE794 and F601
already do, and cover strictly more (module-level duplicates too), so hand-
writing it would be the pathology the gate exists to prevent.

Domains complete: core, accounts, company, CRM, job (core + costing +
kanban/files/PDFs + month-end), timesheets, purchasing, quoting,
accounting/reports (13 `/api/accounting` ops + job month-end GET/POST).

## Open decisions — need YOUR answer

1. **WIP report "as at" semantics (CodeRabbit, PR #22).** For a historical
   `date=` the cost side is bounded by the report date but the invoiced
   amount is not (v1 identical), so invoices issued after the report date
   reduce historical net WIP. Likewise the `total_rev == 0` inclusion gate
   drops cost-only jobs from the `method=cost` view (v1 identical). Both are
   faithful ports whose "fix" changes report numbers — your call whether v2
   should bound invoices by date / gate on the selected method. Declined in
   the PR threads pending your decision.
2. **How ninja partial-update bodies declare optionality — blocks driving the
   nullable gaps to zero.** Of the 146 remaining, **74 are `request.*`**. The
   mechanism exists and is proven: `omittable()` in `apps/core/schemas.py`
   keeps a field optional while making `null` a 422, because presence lives in
   `model_fields_set` and never in the value. Applying it to the other ~40
   PATCH/PUT endpoints is a contract change across every app, so it is your
   call whether that happens before cutover or after. Not urgent for
   correctness — the response-side gaps are the ones publishing a lie — but
   the request side cannot reach zero without it. See the companies_update
   entry in the parity ledger for what one endpoint's conversion looks like,
   including the 400 → 422 move it caused.
3. **Does a 422 belong in the AppError table?** `apps/core/envelope.py`
   persists every `RequestValidationError` (ADR 0019: every handler persists),
   while a service-level client error - the 400 that says "Phone call not
   found" - persists nothing. Nobody chose that split; it falls out of where
   the exception is raised. It surfaced when the uuid work moved malformed
   path ids from the service path to the validation path, so a row now appears
   for input the caller controls: anyone can grow the table by requesting
   `/api/crm/phone-calls/not-a-uuid/`. Either 422s stop persisting, or service
   400s start, or the split gets a recorded reason. Not urgent - the table has
   no size limit and this is not reachable without an authenticated session -
   but it is unbounded client-driven writes, so decide before cutover.
4. **KAN-329 in v1.** v2 is fixed and pinned (ADR 0040); v1 is still broken. One
   line in `purchasing_rest_service.py` if you want it fixed there — awaiting
   your go-ahead, since that is the production repo.

Settled and binding, so do not re-litigate: `parser_version` is the re-parse
marker, and an operator's hand-validation outranks the parser — never overwrite
a validated mapping.

## Environment facts worth knowing

- Steel & Tube login and page selectors are still credential-blocked — they
  have never been exercised against the live portal (cutover checklist item).
- A Gemini API key lives in the local `AIProvider` row: DB only, not in the
  repo or env files. Anything needing the LLM path needs that row.

## Data-migration path: rules and current state

**A v2 migration that writes DATA is useless or harmful on the migrated path.**
Cutover runs `migrate` into an EMPTY database, then restores v1's data, so such
a migration runs before v1's rows exist. Two shapes:

- *Harmful*: `accounts/0003` and `job/0002` seed rows v1's dump also carries,
  colliding on UNIQUE columns; the restore is one transaction, so ONE collision
  rolls back the ENTIRE load. `migrate_v1_data.sh` clears them first.
  A rehearsal only exercises this if its target database actually had the seed
  migrations APPLIED — every rehearsal before 2026-08-05 silently skipped the
  collision because they did not.
- *Useless*: `quoting/0002_normalise_input_data` normalises v1 rows that have
  not arrived yet, so it fixes nothing on this path. NOT harmless — production
  carries 559 double-encoded rows, and after the 2026-08-05 rehearsal they
  landed unnormalised and the product-mappings listing answered 500. The script
  now re-applies it after the restore (its reverse is a no-op, so the same
  tested migration simply runs again with the data present).

  Recorded because the mistake is instructive: this was first written up as
  harmless on the strength of measuring `docketworks_v2`, where normalisation
  had already happened, rather than the v1 source or a restore built the way
  cutover builds one. **Measure the database the claim is about.**

`config/tests/test_data_migration_script.py` **fails if a new data-writing
migration ships unclassified** — that guard is what stops this being re-armed.

**When validation rejects long-standing production data, suspect the model
first.** Of 63 rows found by the 2026-08-04 scan, 32 were never defects:
`Job.company`/`Job.created_by` were `null=True` without `blank=True`, so the
model declared a stricter contract than its own column. The other 31 were
genuine and are repaired in v1 (PR #522, deployed). **Test any destructive
predicate against real data first** — "all 17 blank PO lines are junk" would
have deleted one with $119.50 of stock received against a job.

**`scripts/validate_restored_data.py`** checks a load against the models and
exits non-zero. Sweeps FK orphans (pg_restore `--disable-triggers` skips FK
enforcement), required-but-NULL FKs, and `full_clean()`. It does NOT re-check
CHECK/NOT NULL/UNIQUE — Postgres enforced those during the restore, so a
completed load is already proof.

**PREREQUISITE: v1 PR #522 must be deployed before the final dump.** It
repairs 31 rows that violate v1's own field contracts (17 blank purchase-order
line descriptions, 1 status `void`, 13 out-of-enum `mapped_metal_type`). A dump
taken from an undeployed v1 still carries them.

**State (2026-08-05):** the documented order was rehearsed end to end for the
first time — restore completed, every business table row-count exact, validator
0/0/0. `dw_cutover_rehearsal` holds that clean load. **`docketworks_v2`, which
most tooling still points at, is a STALE pre-fix snapshot** — point real-data
work at the clean one or re-clone.

## Measured risk: the sitemap shard

The scraper reads `sitemap_0.xml` only (v1 did too — inherited, not a
regression). If the catalogue ever spans a second shard, those products become
invisible AND get retired by the discontinue sweep. Measured against the
2026-08-01 restore: **3,677 distinct product URLs**, against a sitemap shard
limit of 50,000 — roughly 7% of one shard, so there is ample headroom today and
this is a monitoring concern, not a live bug. The pre-cutover live-portal run
should confirm the shard count. Defence in place since 2026-08-04: the sweep
refuses to run (and persists an AppError naming the counts) when the sitemap
still lists under 50% of the LIVE catalogue (`MIN_SITEMAP_COVERAGE`) — live
rows only, because retired rows are never deleted and counting them would
decay the ratio until the floor tripped forever. That collapse is the
shard-loss signature; a second shard appearing would trip it instead of
mass-retiring.

## Cross-report divergences (recorded 2026-08-04, accounting slice)

v1's reports disagree with each other on definitions users can see side by
side. Each was ported FAITHFULLY (no silent unification — that would be a
functional change); unifying any of them is a user decision:

- **Working days**: the KPI calendar counts public holidays as working days
  (`kpi_service.py`); the sales pipeline excludes them
  (`sales_pipeline_service.py::_working_days_between`). Both feed
  "per-working-day" numbers shown to the same user.
- **Valid invoices**: WIP counts DRAFT invoices at `total_excl_tax`
  (`wip_service.py`); the sales forecast excludes DRAFT and uses
  `total_incl_tax` (`sales_forecast_service.py`); `invoice_calculation`
  (unported, Job slice) derives all-but-VOIDED/DELETED from the enum.
- **Quote transitions**: job-movement counts EVENTS (a job re-entering
  awaiting_approval counts twice, period bounds are midnight-exclusive of the
  end date); the sales pipeline counts each JOB once with NZ end-of-day
  bounds. "Quotes submitted this month" differs between the two screens.
- **Team billable %**: staff-performance uses the unweighted mean of
  per-staff percentages and includes shop revenue in `total_revenue` while
  excluding shop hours from `billable_hours`; the timesheet screens use
  weighted total-over-total. Same person, different utilisation number.
- **Payroll hours source**: `payroll_reconciliation_service` reads
  `XeroPaySlip.timesheet_hours + leave_hours` (model fields); v1's deferred
  `xero_hours.py` twin (timesheet slice) parses `raw_json` and hardcodes its
  window — when it ports, it must not bring the divergence with it.

Also recorded: v1's `format_period_label` (workflow/api/reports/utils.py) was
dead code with zero call sites — not ported.

## Remaining backend slices

| Slice | Scope | Notes |
|---|---|---|
| process / safety docs | forms, form entries, procedures, JSA/SWP | ~29 ops |
| job chat + MCP | `chat_service`, `mcp_chat_service`, `quote_mode_controller` — all consume the ONE gateway (ADR 0041) | v2 has the `JobQuoteChat` model only |
| quote-to-PO | v1 `purchasing/quote_to_po_service.py`, incl. its inline Gemini client → gateway | |
| search + diagnostics + admin | telemetry writes (deferred from company/kanban/stock search), session replay, app-errors, scheduled tasks, AI providers | |
| **Phase 4: Xero** | sync, push, webhooks, payroll, OAuth callback | Largest remaining risk. Your last free ultrareview is earmarked here. Exact-URL parity required. Verify at port time: a payroll resync that turns a work week into all-leave/unpaid — does v1 delete the now-stale timesheet lines? (CodeRabbit, PR #19, ADR 0007.) |
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
- **Job:** ~~month-end REST screens~~ (DONE, accounting slice 2026-08-04);
  `update_completion_checklist`; weekly-metrics; invoices/quote GET endpoints;
  quote apply/link/preview (Google Sheets sync).
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
4. Test suite is ~6 min serial on 16 cores — parallelise with `pytest-xdist`
   (`--dist loadscope` for the DB fixtures).
5. Root `conftest.py` guard failing any test that attempts a real network call.
   `LLM_BOUNDARY` is module-bound, so a second consumer of `chat_completion`
   silently patches nothing.
6. **No timeout, retry or spend cap at the LLM boundary.** litellm's default
   `request_timeout` is 6000s, so a hung vendor pins a worker for 100 minutes.
   ADR 0041 claims the gateway is where these live; make that true.
7. Rewrite the known-weak tests instead of leaving green-but-meaningless
   assertions: `test_price_extraction.py:48` and `:59` (asserts docstring
   headings; the "no vendor SDK imported" grep uses `f"import {sdk}"` so it
   misses `from mistralai import Mistral` — AST-walk it or replace with an
   import-linter contract), `test_llm_client.py:195` (constant == constant),
   `test_scheduled_tasks_api.py:96` (asserts a hardcoded True),
   `test_stock_metadata_tasks.py:102-155` (mocks the unit under test),
   `test_products_are_saved_in_batches_during_a_long_run` (vacuous — deleting
   the mid-loop flush leaves it green), and
   `test_a_mapping_with_no_item_code_is_simply_not_in_xero` (tautological).
8. Untested paths worth a net: the per-row savepoint in `save_products` (the
   line it really protects is `create_mapping_record`, base.py:447),
   `_save_mapping`'s concurrent-parse branch,
   `scheduled_task_service.py`'s malformed-entry guards, and
   `MAX_FAILURE_RATIO`'s 50% boundary (only pinned to somewhere in (0.6, 0.8);
   `>` vs `>=` untested).
9. `to_optional_decimal` has a pre-existing sibling `_decimal_or_none`
   (`crm/services/phone_call_service.py:1017`) with NO `is_finite()` check,
   writing `Decimal("NaN")` into the call `charge` money column.
10. **Six unrecorded API deviations** to ledger or fix, incl. `render_schedule`
   strings (`5.00 minutes` vs v1's `every 5 minutes`, missing timezone suffix)
   and search not implementing DRF's token splitting (`?search=entry apps.job`
   → v1 120 rows, v2 **0**).
11. **Docstrings that assert behaviour the code does not implement.** Still
   outstanding: the beat-wiring advice and the litellm stub's justification.
   `is_discontinued`'s `help_text` lies, and editing it is a migration while
   v2.0 migrates by pg_dump/restore — so either make the flag mean something
   or drop it before cutover.
12. **Restore the contract strength the port dropped.** One cause, three
   shapes: DRF derived v1's schema from the models, v2 hand-writes all 278
   ninja `Schema` classes and derives nothing, so weaker declarations
   accumulated with no drift entry — nobody chose them, nothing was watching.
   `scripts/schema-contract-gaps.txt` IS the work list, **152 entries**, and it
   ratchets down to zero (ADR 0044). Counts below are measured from that file,
   not carried forward in prose; regenerate them from it rather than editing:
   - **146 `nullable`** — v1 guarantees a value, v2 admits null. Split
     **74 `request.*` / 72 `response*`**, and the two halves are different
     problems. The response ones are the real weakening: `GET
     /api/job/jobs/{}/ :: response:200.data.job.latest_estimate` publishes as
     nullable while `Job.latest_estimate` is `null=False` in v2's own model,
     so every consumer handles a case that cannot occur. Many of the request
     ones are the partial-update spelling — `PATCH
     /api/companies/{}/update/ :: request.name` is optional in both schemas
     and merely spelled `anyOf[str, null]` by ninja — which is the same
     artefact deliberately excluded for query parameters. **Reaching zero
     therefore needs a decision on how ninja partial-update bodies are
     declared, not just bug-fixing.** Per gap the test is **"can the v2
     producer emit None"**, not "what does the model say" — a service that
     really can return `None` is a divergence for the ledger, and the entry
     stays in the gaps file with the ledger explaining it.
   - **0 `uuid`** — closed 2026-08-07. The 12 CRM path parameters are typed
     `UUID` now, so a malformed id is a 422 at the boundary instead of a 400
     or 404 chosen per endpoint; see the ledger entry for the behaviour change
     and `apps/crm/tests/test_phone_call_api.py`
     `TestMalformedPathIdIsRejectedAtTheBoundary` for what it means. The other
     four were response/query ids typed `str` where the model holds a UUID.
   - **6 `required`** — v1 guarantees the property is present, v2 makes it
     optional.

   Request-side tightening changes runtime validation (a payload that passed
   starts returning 422), but it tightens *toward v1*, which is what the
   production frontend already satisfies. The frontend generates from
   `schema.v2.yml`, so regenerating turns each tightening into a TypeScript
   error at build rather than a runtime surprise.
13. **Service TypedDicts declaring `str` ids whose wire mirror says `UUID`.**
   Four in `apps/company/services/person_service.py` are fixed
   (`PersonCompanyLinkData`, `PhonePersonMatchData`, `PhoneCompanyOwnerData`,
   `PersonCompanySummaryData` — three of them were coercing a real `UUID`
   through `str()` to satisfy their own annotation).
   **`apps/company` is not finished:** `services/duplicate_identity_report.py`
   carries five more of exactly this shape: `DuplicateCompanyMember.company_id`,
   `DuplicatePersonSummary.person_id`, `DuplicatePersonCompanyLink.link_id`
   and `.company_id`, and `DuplicatePersonContactMethod.method_id`. Each
   mirror in `schemas.py` (`DuplicateCompanyMemberOut` and friends) declares
   `UUID`.
   The duplication gate only surfaced the first four because two of them
   happened to collide on a name, and **the parity diff cannot see this class
   at all** when the wire schema is already correct. Finding the rest means
   reading each app's `services/*.py` TypedDicts against its `schemas.py`.
   (`company_rest_service.py` and `duplicate_phone_report.py` also hold `str`
   ids, but their wire mirrors say `str` too — those are the uuid-gap class,
   already in the gaps file.)
14. **Three defects the handler-gate annotation surfaced (PR #26 review).** All
   three are pre-existing code that the marker audit drew attention to; each
   was confirmed by CodeRabbit and deliberately deferred so a behaviour change
   would not ride inside a PR about a test gate.
   - `apps/job/services/time_entry_rates.py:76` — `to_decimal(value,
     default=...)` maps an unparseable value to the default, and
     `price_time_entry` feeds it `meta["wage_rate_multiplier"]` straight from
     stored CostLine metadata, so garbage prices a wrong cost line (ADR 0015).
     Fix: **absent** keeps the default, **present but unparseable** raises.
     Measured **0 malformed of 13,931** rows carrying either multiplier, so no
     repair migration — re-confirm against `dw_cutover_rehearsal`, not the
     stale `docketworks_v2`. `test_time_entry_rates.py:45` asserts the fallback
     today and becomes an expectation of a raise.
   - `apps/crm/services/phone_call_service.py` `_positive_int` — `float("inf")`
     passes the isinstance gate and `int(float("inf"))` raises `OverflowError`,
     so the documented "unparseable duration is zero" contract is false and the
     call crashes. Reject non-finite floats up front rather than widening the
     `except`. (`float("nan")` raises `ValueError` and is already caught.)
   - `apps/job/models/job.py:688` `has_quote` — catches bare `AttributeError`.
     `RelatedObjectDoesNotExist` subclasses both that and `ObjectDoesNotExist`,
     so it works but equally swallows a genuine typo. Catch
     `ObjectDoesNotExist`, already the pattern at `kanban_service.py:520`.
15. **`X | None` returns: 113 of 1315 non-test functions (9%)** — job 30,
   quoting 20, accounting 16, company 16, timesheet 11, core 8, purchasing 6,
   crm 4, xero 2. That is every app, and the nine sum to 113; an earlier
   revision listed only the top six against a total of 110, so the list looked
   exhaustive while omitting 12 sites. Counted as unions where `None` sits
   beside a real type at the TOP level of the annotation — a bare `-> None` is
   a procedure, and `tuple[Company | None, ...]` or `Status[None] | Data`
   (the error envelope) never return `None` themselves. ADR 0045 makes this a
   rule going forward; the existing sites are a post-cutover sweep, not a
   blocker. Each one moves a decision onto every caller, and there are always
   more callers than functions.
16. **PR #26's final commit `72a7118` was never reviewed** — CodeRabbit hit its
   rate limit, and that commit is the one closing four holes in the handler
   gate. Three earlier review rounds each found real holes in that same file
   (eleven in total), so treat `config/tests/test_exception_handler_contract.py`
   as the least-reviewed part of the gate suite and re-review it when the
   deferred fixes above touch it.
17. Cosmetic: `base.py:352` fetches all known URLs then discards them when
   `refresh_old`; `scheduled_task_service.py:119` has an unreachable-false
   guard; `llm_client.py:80` truthiness-tests a `str | None`;
   `llm_client.py:116` sets a module global on every call.

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
- **Job aging silently served corrupt data unsorted** — a NULL-staff actual
  time line (impossible to write in v2; possible in restored v1 data) made
  v1 blank that job's activity fields and then swallow a sort TypeError,
  returning the whole report unsorted. v2 stops loudly instead (user
  decision 2026-08-04, ADR 0015); the production restore has zero such rows
  (verified 2026-08-04, 0 of 12,686 actual time lines).
- **Job aging `days_in_current_status` never worked** — v1 filters JobEvents
  on `event_type="status_change"`, but the tracker writes `"status_changed"`,
  so the branch is dead and every job silently reports days-since-creation.
  Fixed in v2 (ledgered); v1 unfixed.
- **The RDTI spend endpoint 500s on every call in v1** — its response
  serializer validates `rdti_type` against `RDTIType.choices` while the
  service always emits an "unclassified" summary row, so serializer
  validation fails on every request. The endpoint has never returned data.
  Works in v2; v1 unfixed.
- **Month-end POST error reporting was unreachable in v1** — the service
  returns `(job_id, message)` tuples but the serializer declares
  `errors: list[str]`, so any per-job failure blew up the whole response
  instead of reporting it. v2 serves the declared contract.
- **Staff-performance summary 500s on any empty period in v1** — the
  empty-team branch returns only 4 of the 8 keys its own response serializer
  requires, so a date range with no recorded hours (any weekend) has never
  returned. v2 returns 200 with zeroed averages (ledgered); v1 unfixed.
- **Payroll reconciliation 500s opaquely on a nameless pay slip** — a
  XeroPaySlip with no `employee_name` and no matching Staff keyed a row on
  `None` and failed in the serializer. v2 fails loudly with the slip named
  (persisted AppError).
