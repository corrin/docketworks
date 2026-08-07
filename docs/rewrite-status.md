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

Last updated: 2026-08-07 NZ (static contract deleted; work re-sequenced around
E2E and the 15 Aug cutover).

## Cutover: Saturday 15 August 2026

**The date is immovable; scope bends.** Three non-negotiables:

1. **Every E2E test passes.** No E2E, no release.
2. Release that weekend.
3. The code must improve — racing bad code into production defeats the point.

## Where things stand

| Measure | Value |
|---|---|
| **E2E specs passing** | **1 of 40** (`login`) — the only measure of "ported" |
| E2E test cases | 136 across those 40 files |
| Backend operations still to port | **99** (see below; 32 more exist but nothing calls them) |
| Unit tests | 1262 (all passing) |
| Coverage | 91.12% (floor 88, ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, zero `type: ignore`, all gates on every commit |
| Behaviour ledger | 69 recorded deviations |
| ADRs | 32 (v1's 26 carried forward + 0038–0041, 0043, 0045 written here) |

**Written is not ported.** 175 operations exist in `apps/` and none has been
exercised end to end, so by rule 1 above none is done. Report progress as specs
green; a count of endpoints written measures typing, not delivery.

The standing gates are ruff, mypy (strict, zero baseline), import-linter,
makemigrations --check, deptry, **find-duplicates** and the frontend trio, all
on pre-commit; CI adds the exported-schema freshness check.
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

**It has never been pointed at a frontend.** v1's carries the same pathology it
was built to catch — `admin-company-defaults-service.ts`,
`company-defaults.service.ts` and `companyService.ts` sit in one directory under
three naming conventions. Run it over `frontend/src/` as that tree grows, or the
rewrite reproduces exactly what it was meant to escape.

Domains **written** — none E2E-verified, so none is finished: core, accounts,
company, CRM, job (core + costing + kanban/files/PDFs + month-end), timesheets,
purchasing, quoting, accounting/reports (13 `/api/accounting` ops + job
month-end GET/POST).

## Open decisions — need YOUR answer

1. **WIP report "as at" semantics (CodeRabbit, PR #22).** For a historical
   `date=` the cost side is bounded by the report date but the invoiced
   amount is not (v1 identical), so invoices issued after the report date
   reduce historical net WIP. Likewise the `total_rev == 0` inclusion gate
   drops cost-only jobs from the `method=cost` view (v1 identical). Both are
   faithful ports whose "fix" changes report numbers — your call whether v2
   should bound invoices by date / gate on the selected method. Declined in
   the PR threads pending your decision.
2. **DECIDED 2026-08-07: a client error IS an AppError, and the rule goes
   further than the question asked.** A caller sending data the contract forbids
   is a defect worth a row, so 422s keep persisting. The harder half: a
   well-formed id matching no row is ALSO recordable. `PhoneCallRecord` is
   append-only — nothing in `apps/` deletes one, the four CRM DELETE routes
   remove a job-link, a recording file, a provider-side recording and an
   endpoint — so "Phone call not found" can only mean a client bug, id probing,
   or an id from another environment. There is no benign fourth case. For a
   genuinely deletable resource an absent target can be two users racing, but
   that costs one row to log while an invisible client bug costs the ability to
   ever see it. **Consequence, not yet implemented:** the 12 assertions across 6
   files that say a client error must leave no AppError encode the wrong rule
   and need inverting, and `TestClientErrorsDoNotPersistAppErrors` needs
   renaming. Its own slice — see the backlog.
3. **KAN-329 in v1.** v2 is fixed and pinned (ADR 0040); v1 is still broken. One
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

**`scripts/ops/validate_restored_data.py`** checks a load against the models and
exits non-zero. Sweeps FK orphans (pg_restore `--disable-triggers` skips FK
enforcement), required-but-NULL FKs, and `full_clean()`. It does NOT re-check
CHECK/NOT NULL/UNIQUE — Postgres enforced those during the restore, so a
completed load is already proof.

**v1 PR #522 is DEPLOYED (2026-08-07)** — it repaired 31 rows violating v1's own
field contracts (17 blank purchase-order line descriptions, 1 status `void`, 13
out-of-enum `mapped_metal_type`). The consequence that still bites: **every dump
taken before 2026-08-07 still carries those rows**, so take a fresh one for
cutover and rebuild the rehearsal database from it.

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

## Remaining backend work: 99 operations

Derived by cross-referencing every `api.*` call in v1's frontend against what
v2 exposes. v1's app calls 231 operations; **99 of them are unported**. The
grouping is by the screen each serves, because that is how a spec goes green —
a URL-prefix count does not tell you which page is blocked.

**Regenerate rather than trust this list** as work lands: extract `api.*` call
sites from the frontend, diff against v2's `frontend/schema.v2.yml`, and read
v1's contract from `../docketworks/frontend/schema.yml` — this repo no longer
carries a copy.

### Blockers — these fail EVERY spec at once

`tests/fixtures/auth.ts` fails a test on any unexpected browser console error,
and these load on every page, so until they exist no spec can pass and every
failure looks like a different bug.

| Operation | Called by |
|---|---|
| `data_versions_retrieve` (`GET /api/data-versions/`) | `composables/useDataFreshness.ts`; `App.vue` polls it on every tab-focus |
| `workflow_notebook_lm_links_menu_list` | the navbar, on every page |
| `workflow_xero_pay_items_list` | a store; also referenced directly by `job-cost-entry-data.spec.ts` |
| company-defaults ×3 (`retrieve`, `partial_update`, `schema_retrieve`) | `stores/companyDefaults.ts`; `company-defaults.spec.ts` |

### The rest

| Group | Ops | Unblocks |
|---|---|---|
| Staff — list, all, create, partial_update, icon_create | 5 | `staff/create-staff`, `staff/staff-wage-loading` |
| Job — timesheet entries, finish (×2), invoices | 4 | `job/job-cost-entry-data`, job finish tab |
| Job — quote (retrieve, status, apply, link, preview) | 5 | job quote tab |
| Job — quote-chat | 5 | job chat; routes through `apps/ai` (ADR 0041) |
| Job — weekly-metrics, workshop, completed, completed/archive, archived-jobs-compliance, job-profitability | 6 | reports, workshop views |
| **Xero** — sync, sync-info, ping, disconnect, create/delete invoice, create/delete quote, create PO, branding-themes | 11 | `job/job-xero-invoice`, `job/job-xero-quote` |
| Xero errors | 5 | admin error views |
| Xero apps | 5 | `XeroAppSettings.vue` |
| **Process documents** — forms (9), procedures (8), safety-ai (4), jsa (2) | 23 | `process-documents/form-entries-page-scroll`, JSA/SWP |
| App errors (incl. `rest/app-errors`) | 5 | `AdminErrorView.vue` |
| AI providers | 6 | `AdminAIProvidersView.vue`; must route through `apps/ai` (ADR 0041) |
| Session replays | 5 | session replay admin |
| Operations — workshop-schedule, recalculate | 2 | `pages/schedule.vue` |
| Search events — click | 1 | search telemetry, deferred from the search slices |

**Xero is the largest risk** and keeps exact-URL parity — Xero holds the
redirect and webhook URLs. Your last free ultrareview is earmarked here. Answer
at port time (CodeRabbit PR #19, ADR 0007): when a payroll resync turns a work
week into all-leave/unpaid, does v1 delete the now-stale timesheet lines?

### Do NOT port: 32 operations nothing calls

A further 32 unported operations have **zero call sites in v1's frontend** —
dead surface, and porting them is work that no spec can ever verify. v1's own
ledger already records one (`accounts_token_verify_create`, "referenced only by
the generated client"). Confirm a call site exists before porting anything not
in the table above.

## Remaining non-API work

| Item | Notes |
|---|---|
| Frontend SPA | React/TanStack; `frontend/` has 5 routes and one real page against v1's 62. v1's 40 specs port here — see the E2E section below |
| quote-to-PO | v1 `purchasing/quote_to_po_service.py`, incl. its inline Gemini client → the gateway |
| Middlewares | AccessLogging, DisallowedHost, **FrontendRedirect** (serves the SPA — needed, not optional), PasswordStrength |
| Ops | Dropbox API sync, deploy scripts |

## Porting the E2E suite

v1 has **40 spec files / 136 `test()` cases**; v2 has one (`login`). What
carries over and what does not:

- **Reproduce v1's `data-automation-id` values in the new components.** v1 has
  342 distinct ids across 68 files, and 63 of its 294 selectors use them — that
  fraction ports unchanged. So do 53 `getByRole` and 22 `getByText`. The
  remainder (118 structural, 37 css/id) is what needs rewriting.
- **`tests/scripts/` ports as-is** — DB backup/restore, sequence sync, safety
  checks are all database-level. So do `playwright.config.ts` and the auth
  fixture's API login (`POST /api/accounts/token/` → `access_token` cookie).
- **Raise `maxFailures` when triaging.** It is 1 by default, which hides 39
  failures behind the first.
- `global-setup.ts` runs its own DB backup/restore; v2's equivalent is
  `scripts/ops/migrate_v1_data.sh`. Reconciling them is the known time sink.

Six specs have a **proven** unported dependency (from their `waitForResponse`
URLs): `company-defaults`, `job/job-cost-entry-data`, `job/job-xero-invoice`,
`job/job-xero-quote`, `process-documents/form-entries-page-scroll`,
`staff/create-staff`. The rest reach endpoints through the UI, so only running
them reveals what they need.

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
12. **The contract is verified by E2E, not by comparing against v1.** v1's
   frozen schema, the parity gate and the 152-entry gaps ratchet are deleted.
   The ratchet asked "is v2 weaker than v1", which treats v1's contract as
   something to preserve when v1 is being replaced precisely because it was
   wrong — and it could never reach the zero it claimed, because its own rule
   required deliberate divergences to stay listed forever. v1's schema remains
   a useful *reference* while porting (probably right most of the time; v1's
   live code at `../docketworks` is a better one than a fork-commit freeze),
   but it is not an authority and nothing gates on it.

   What verifies the contract now, in order: the backend types produce
   `frontend/schema.v2.yml`, CI fails if the committed client is stale against
   it, `tsc` compiles the frontend against those generated types, and E2E
   exercises the result. The first three catch shape; only E2E catches
   behaviour. **E2E is at 0%** — one spec ported of v1's 45 — so by the rule
   that an unverified backend is assumed wrong, the contract is currently
   unverified. Porting E2E is what fixes that; no static gate can.
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
