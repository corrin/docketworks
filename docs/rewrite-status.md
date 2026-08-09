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

Last updated: 2026-08-10 NZ (the timesheet-entry slice landed: daily overview
+ entry pages, SmartTimesheetTable over the shared draft machinery extracted
from the cost grid, `job_timesheet_entries_retrieve` + `accounts_staff_list`,
and five specs green — `create-timesheet-entry`, `keyboard-nav`,
`urgent-job-defaults`, `performance`, `staff-wage-loading`. Also that day: the
delivery plan gained explicit MUST / SHOULD / DEFERRED tiers, AI is SHOULD
before cutover, and the all-MUST-work-complete milestone is the release gate).

## Cutover: Saturday 15 August 2026

**The date is immovable; scope bends.** Three non-negotiables:

1. **Every MUST-tier E2E test passes.** A red MUST spec means no release.
2. Release that weekend.
3. The code must improve — racing bad code into production defeats the point.

### Delivery tiers

| Tier | Meaning | Scheduling rule |
|---|---|---|
| **MUST before cutover** | The release is unsafe or unusable without it | Release-blocking; always the next work while any MUST item is open |
| **SHOULD before cutover** | Valuable pre-cutover scope that is not required for a safe release | Pick up only when it cannot put the MUST milestone at risk |
| **DEFERRED until after cutover** | Explicitly outside the cutover scope | Do not pick up before release |

**AI is SHOULD before cutover, not MUST.** This includes quote chat, safety AI,
AI-provider administration, NotebookLM CRUD, the quote-to-PO AI path, and the
production-safety work at the shared LLM gateway. Existing boot plumbing under
`/api/ai/` is already done and remains part of the application shell; this tier
controls the unfinished AI product work.

**Deferred (decided 2026-08-09):** go-live needs neither process documents nor
the remaining reports — the `process-documents/form-entries-page-scroll`,
`sales-forecast` and `payroll-reconciliation` specs, plus the no-spec job-reports
group. The `example` spec is a placeholder to delete, not release scope.
Every other spec in the E2E table is MUST unless this section explicitly moves
it to another tier.

### Milestone: all MUST tasks complete

- [ ] Every MUST-tier E2E spec is green.
- [ ] Every backend and frontend slice required by those specs is complete.
- [ ] The production-serving path is complete, including `FrontendRedirect`
      and deployment scripts.
- [ ] Every unchecked release-gate, data-prerequisite, migration, environment,
      and live-integration item in `docs/cutover-checklist.md` is complete.

**This milestone is the go/no-go gate.** SHOULD work is still targeted before
15 August, but an incomplete SHOULD item does not hold the release and never
displaces an open MUST item. DEFERRED work starts only after cutover.

## Where things stand

| Measure | Value |
|---|---|
| E2E specs ported | **21 of 40** — green is the only measure that counts |
| Backend operations still to port | **72** (see below; 32 more exist but nothing calls them) |
| API operations v2 exposes | 204 (`frontend/schema.v2.yml`, kept fresh by its own gate) |
| Unit tests | 1731 (all passing) |
| Coverage | 88.56% (floor 88, ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, zero `type: ignore`, all gates on every commit |
| Behaviour ledger | 84 recorded deviations |
| ADRs | 33 (v1's 26 carried forward + 0038–0041, 0043, 0045–0046 written here) |

**Written is not ported.** Every operation in `apps/` is unexercised end to end,
so by rule 1 above none is done. Report progress as specs green; a count of
endpoints written measures typing, not delivery.

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

## Gotchas — read before picking up a slice, not after

Each of these is invisible until it costs a day, and each was measured rather
than guessed. Details sit with the slice that owns them; this is the index.

1. **22 of the 40 specs cannot reach their assertions until one UI flow works.**
   Their fixtures build test data by *driving the browser* —
   `AppNavbar-create-job` → `/jobs/create` → `CompanyLookup` →
   `PersonSelectionModal` → submit. Not by seeding over the API. A spec in the
   job, kanban or timesheet clusters is not "blocked on its endpoints", it is
   blocked on that flow.
2. **`company-defaults` blocks far more than its own spec.** `JobViewTabs`
   renders `JobEstimateTab` only under `v-if="companyDefaults"`, so the whole
   job cluster is dark until it exists.
3. **Every `console.error` fails a test.** The guard is ON in v2's fixture
   (`tests/e2e/fixtures/auth.ts`): any unexpected browser console error or
   uncaught page exception fails the test. New code must route TanStack Query
   error logging and React error boundaries to toasts, or bring a per-spec
   whitelist (`test.use({ expectedConsoleErrors: [...] })`).
4. **Kanban's 5 specs use almost no `data-automation-id`s** — three of them use
   zero. They bind to `[data-status]`, `[data-job-id]`, `[data-staff-id]`,
   `.mobile-status-pill`, `.staff-item`, `:visible` and `..` parent traversal
   (`KanbanColumn.vue:19,98`, `JobCard.vue:17,18,103`). The React port must
   reproduce the attribute names, the class names **and the nesting depth**, or
   assertions break silently rather than loudly.
5. **`[data-is-clone]` is a sortablejs artefact** (`kanban.vue:652,672,673`),
   asserted by two drag specs totalling 808 lines. dnd-kit produces no clone
   node — pick the drag library to satisfy the selector, not by preference.
6. **`@kodeglot/vue-calendar` has no React equivalent.** It backs
   `workshop-my-time-view`. Rebuild or rewrite the spec; it is not a port.
7. **`timesheet/performance.spec.ts` asserts wall-clock budgets** — a query
   waterfall fails it even when the page is correct.
8. **`getPhantomRowIndex()` (`helpers.ts:228`) requires a trailing empty row**
   in `SmartTimesheetTable`, discovered via `DataTable-row-N`.
9. **5 specs touch a live Xero tenant** (see the E2E table — four rows once
   said "yes" wrongly; they only read restore-populated mirror tables). The
   teardown waits `PRE_RESTORE_XERO_SETTLE_MS = 90_000` before restoring.
10. **Generated types are camelCase** (`user.fullName`). v1's snake_case field
    access does not transfer, and the generated TanStack exports are *option
    factories*, not hooks.
11. **`maxFailures: 1` plus 11 `test.describe.serial` files** means one early
    failure hides most of the suite twice over. Raise it when triaging.
12. **Only two kinds of number belong in this file, because it is throwaway.**
    It is deleted at cutover, so any number needing manual upkeep is effort
    spent maintaining something about to be thrown away.
    - *Moves as v2 progresses* — **derived and gated**, owned by the table:
      specs ported, operations still to port, operations v2 exposes.
      `status_table.py` computes them and `--check` fails on a table row or a
      sentence that disagrees. Free to keep correct. Never type one by hand.
    - *Frozen fact about v1* — exact, stated once. v1 does not change for the
      rest of the port, so 40 spec files, the 22 blocked behind create-job and
      every v1 line count below cannot rot.

    **Estimates of work not yet done do not belong here at all** — a forecast
    cannot be derived and cannot be checked, so it rots by construction and
    costs attention to maintain for no gain. Say which thing is bigger, not by
    how much. The one survivor is `Coverage`, which needs a coverage run;
    it is hand-maintained and can still go quietly wrong.

## Open decisions — need YOUR answer

0. **Cost-line write auth is looser than the timesheet reads (found in the
   timesheet-entry slice review; predates it).** The management reads
   (`/api/timesheets/*`, `/api/job/timesheet/entries/`, `/api/accounts/staff/`)
   are superuser-only because they expose wage data — but the write path the
   entry grid (and the cost-entry slice before it) uses is plain
   authenticated: `job_jobs_cost_sets_actual_cost_lines_create` accepts an
   arbitrary `staff` UUID with no ownership check, and cost-line PATCH/DELETE
   are likewise open, so any authenticated staff member can attribute, edit
   or delete a colleague's time line — bypassing the ownership rule the
   self-service workshop endpoints enforce. `job_jobs_cost_sets_retrieve`
   also serves every time line's wage-loaded `unit_cost` to any staff.
   Tightening mid-week risks the workshop flows, so nothing changed in the
   slice; your call whether cost-line writes gate on office/superuser (or
   ownership) before or after cutover.

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

Settled and binding, so do not re-litigate: `parser_version` is the re-parse
marker, and an operator's hand-validation outranks the parser — never overwrite
a validated mapping.

## Environment facts worth knowing

- Steel & Tube login and page selectors are still credential-blocked — they
  have never been exercised against the live portal (cutover checklist item).
- A Gemini API key lives in the local `AIProvider` row: DB only, not in the
  repo or env files. Anything needing the LLM path needs that row.
- The E2E user (`E2E_TEST_USERNAME` in `frontend/.env.test`) must have
  `is_office_staff = true` — the navbar's Create Job link is gated on it, so
  every job-cluster spec silently stalls without it, and a freshly restored
  database does not have it set.
- The E2E user must also have a **non-zero `wage_rate`** (set to 45.00 in the
  dev DB, 2026-08-09) — `job-cost-entry-data` seeds a timesheet labour line
  for the authenticated user, and the pricing pipeline refuses loudly on an
  unconfigured wage. Same class as the flag above: a fresh production restore
  does not carry it.
- The E2E user must be a **superuser** (set in the dev DB, 2026-08-10) — the
  timesheet management surface (`/api/timesheets/*`,
  `/api/job/timesheet/entries/`, `/api/accounts/staff/`) is superuser-only,
  so every timesheet-cluster spec 403s without it. Same fresh-restore class
  as the two flags above.
- The timesheet specs additionally rely on restore data that already holds:
  an **"Annual Leave" job** findable by name in the picker whose default pay
  item is the Annual Leave pay item, `annual_leave_loading > 0` in company
  defaults, and at least one active staff member with `base_wage_rate > 0`.

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

## Remaining backend work

The count is in the table above and is **derived, not typed**: v1's operation
surface is frozen in `scripts/v1-frontend-operations.yml`, and
`scripts/checks/status_table.py` subtracts the live `frontend/schema.v2.yml`
from it. Porting an operation lowers the number with no edit to any file, and
`--check` fails if the table or a sentence disagrees. Nothing below needs
counting by hand.

That file is a **work list, not a contract authority**. It records which
operation names v1's frontend called; it never says what shape v2 must serve.
Commit `5cefdc5` deleted the parity ratchet for making v1 authoritative, and
nothing here can fail a build because v2 is different from v1 — only because v2
has drifted from its own record of what is left.

**Renames are the one thing you must record by hand.** `export_openapi.py` pins
dissolved v1 app names at zero, so every called `workflow_*` operation gets a
new name when it ports — 17 still to come. Add each to `renamed:` as you go: an
unrecorded rename makes the v1 name read as still-missing *and* the v2 name look
like a brand-new endpoint, corrupting the count in both directions at once. The
gate catches this without ever seeing v1, by failing on any v2 operation with no
v1 ancestor and no entry saying why.

The grouping below is by the screen each operation serves, because that is how a
spec goes green — a URL-prefix count does not tell you which page is blocked.

### Reading the readiness marks

Each group below carries **Models / Services / Router**, because the difference
between them is the difference between an afternoon and a week, and the old
one-line-per-group table could not show it. The decisive fact: `config/api.py`
registers **10 routers** — accounting, accounts, company, core, crm, job,
**operations**, purchasing, quoting, timesheet. `apps/xero`, `apps/process`,
`apps/search` and `apps/diagnostics` have `models/` plus
`migrations/0001_initial.py` and **nothing else** — no `api.py`, no `schemas.py`,
no `services/`. They exist so v1's `pg_dump` restore lands in tables Django
knows about (hence the `db_table = "workflow_*"` overrides), not because the
domain is started. **No group below is "backend done, needs only frontend."**

### Blockers — these fail EVERY spec at once

`tests/fixtures/auth.ts` fails a test on any unexpected browser console error,
and these load on every page, so until they exist no spec can pass and every
failure looks like a different bug.

| Operation | Called by | Models | Services | Router |
|---|---|---|---|---|
| ~~`data_versions_retrieve`~~ | — | **DONE** `195dc6c` — lives in `apps/operations`, not beside build-id in `apps/core`, because every provider reads a domain model and core sits below the domain apps | | yes |
| ~~`workflow_notebook_lm_links_menu_list`~~ | the navbar, on every page | **DONE** — served as `notebook_lm_links_menu_list` under `/api/ai/` (ADR 0041): the navbar reads a menu, so there was nothing to preserve of v1's `workflow` prefix | | yes |
| ~~`workflow_xero_pay_items_list`~~ | a store; also referenced directly by `job-cost-entry-data.spec.ts` | **DONE** — served as `xero_pay_items_list` at `/api/xero/pay-items/`, NOT v1's `/api/workflow/…`: no external party holds the URL, so there is nothing to preserve and no reason to import a dead app's name | | yes |
| ~~company-defaults ×3 (`retrieve`, `partial_update`, `schema_retrieve`)~~ | `stores/companyDefaults.ts`; `company-defaults.spec.ts` | **DONE** — retrieve/patch in `apps/core/api.py`; `schema_retrieve` serves the settings field registry (`apps/core/settings_metadata.py`), enforced at boot by checks E001–E003. Serves no empty sections: the ledger records the dropped leftover `crm` one | | yes |

All four exist, so every page can boot. The critical-path flow (navbar →
`/jobs/create` → `CompanyLookup` → `PersonSelectionModal` → job detail shell)
and the harness prerequisites landed with the `create-job` slice, so the
job/kanban/timesheet clusters are no longer flow-blocked — what each spec still
needs is its own components plus the `sharedEditJobUrl` worker fixture
(13 specs; not yet ported).

### The rest, per group

**Staff.** ~~`accounts_staff_list`~~ (**DONE**, timesheet-entry slice — shipped
ahead of this group because `staff-wage-loading` reads it; superuser-only,
whole staff table incl. departed, via `staff_directory.list_all_staff`),
`_all_list`, `_create`, `_partial_update`, `_icon_create`.
Models present: `Staff` incl. the `icon` ImageField (`apps/accounts/models.py:68,76`) ·
Services partial: `staff_directory.py` (`get_displayable_staff`, `list_all_staff`) ·
Router partial: `apps/accounts/api.py` now also registers the list.
Remaining ops unblock `staff/create-staff`. `_icon_create` is a
multipart upload — the only one in this group.

**Job — timesheet entries.** ~~`job_timesheet_entries_retrieve`~~ — **DONE**
(timesheet-entry slice): homed in `apps/timesheet/api.py` keeping the `job_*`
operation ID and the `/api/job/timesheet/entries/` URL, superuser auth like
its management siblings; CostLine-shaped lines with a per-line job-identity
overlay (`job_service.cost_line_data` + job fields), staff block,
`entry_count` + `scheduled_hours` in the summary. The three dead
modern-timesheet siblings (`entries_create`, `jobs_retrieve`,
`staff_date_retrieve`) were confirmed dead surface and NOT ported.
**The timesheet daily + entry screens are built and their five specs are
green.** Deferred with seams (no spec asserts them): StaffDetailModal,
MetricsModal, the entry page's Current Jobs cards (v1's per-job getJobSummary
N+1 wave), the help dialog, container-level grid keyboard shortcuts
(Ctrl+Enter add / Ctrl+Backspace delete / arrow row selection).
`timesheet/workshop-my-time-view` remains its own slice — the calendar
rebuild (`@kodeglot/vue-calendar` has no React equivalent).

**Job — quote.** `job_jobs_quote_retrieve`, `_status_retrieve`,
`_apply_create`, `_link_create`, `_preview_create`.
Models present: `QuoteSpreadsheet` (`apps/job/models/spreadsheet.py:9`) ·
Services partial: accept and revise exist (`apps/job/api.py:519,650,669`); apply/link/
preview are Google Sheets sync and are deliberately deferred (`apps/job/api.py:12`) ·
Router partial. The Sheets dependency is the real cost here, not the endpoints.

**Job — quote-chat (SHOULD before cutover; AI).** `job_jobs_quote_chat_retrieve`, `_create`,
`_partial_update`, `_interaction_create`, `quote_chat_delete_all`.
Models present: `JobQuoteChat` (`apps/job/models/job_quote_chat.py:11`) ·
Services none `apps/ai/services/` holds only `llm_client.py` · Router not registered.
Must route through `apps/ai` (ADR 0041) — v1 grew four parallel vendor clients
by not doing this. No spec covers the chat tab, so it is stubbable for E2E.

**Job — reports.** `job_jobs_weekly_metrics_list`,
`job_jobs_workshop_list`, `job_job_completed_list`,
`job_job_completed_archive_create`, `check_archived_jobs_compliance`,
`job_profitability_report`.
Models present: Job/CostLine/JobEvent · Services none **none** — the only trace is a v1
pointer comment at `apps/job/models/job.py:143` naming
`JobRestService.get_weekly_metrics()` · Router not registered. Each is a fresh aggregation
service, not a route over existing logic. No spec gates any of them, and
go-live does not need them (bend-first list under Cutover).

**Xero.** `xero_sync_create`,
`_sync_info_retrieve`, `_ping_retrieve`, `_disconnect_create`,
`_create_invoice_create`, `_delete_invoice_destroy`, `_create_quote_create`,
`_delete_quote_destroy`, `_create_purchase_order_create`,
`_branding_themes_list`.
**Slices 1 (xero/foundation) and 2a (xero/sync-engine) are DONE**: OAuth client + token store
(`apps/xero/auth.py`, refresh lock, rate-limited client, active-app swap),
the provider registry (`apps/accounting/{provider,registry,types}.py`, ADR
0012 inversion, XERO_READONLY swap), contact push, `get_company_for_xero`,
company create/update through the provider, plain-Django OAuth views at the
exact-parity `/api/xero/authenticate/` + `/api/xero/oauth/callback/` URLs,
and ninja `xero_ping_retrieve` / `xero_disconnect_create` /
`xero_branding_themes_list` / the `xero_apps` group. E2E harness preflight +
token save/reinject are live; `job/create-job-with-new-company` is the
proving spec.
**Slice 2a (xero/sync-engine) is DONE**: the full sync engine (all ten
entities + pay_items, per-page quota floor, cursors), transforms +
raw-field derivation, webhook receiver at the exact-parity
`/api/xero/webhook/` (HMAC-auth, middleware-allowlisted), the three beat
entries (heartbeat */5, hourly :15, deep-sync Sat 02:00 — the worker gates
whole runs on XERO_READONLY), outbound stock push, sync trigger/sync-info
ninja ops + the plain SSE view, the e2e-sync-windows mechanism, and two
ledgered v1-defect fixes (batch-path unarchive→allow_jobs restore;
phone-conflict AppError persisted after the rollback). ADR 0007's payroll
resync question is ANSWERED and ledgered: pay-slip sync never touches
timesheet lines — the deletion question belongs to the deferred payroll
push.
**Slice 2b (DONE 2026-08-09, `job-xero-invoice` green → 13/40):** document
manager base + invoice push (`documents/{base,invoice}.py`, provider
create/delete_invoice + readonly fabrications, `POST /api/xero/
create_invoice/{job_id}` + `DELETE /api/xero/delete_invoice/{job_id}` at
v1-parity URL fragments), PO push (`documents/po.py`, provider PO upsert
with zero-UUID recovery, create/delete PO endpoints — no spec; unit tests
are its gate), Finish Job backend (`apps/accounting/services/
finish_job_summary.py`, checklist service, `job_jobs_finish_retrieve/
_partial_update`, `job_jobs_invoices_retrieve`), and the React
JobFinishTab/JobInvoiceCard with the spec's automation ids.
Readonly-works-by-construction: the endpoint path is identical under
XERO_READONLY; the provider fabricates well-formed results (INV-E2E-*
numbers, GST-exclusive fake totals) and `recalculate_job_invoicing_state`
runs in the same request (ledgered — v1 left the flag to the hourly sync).
Also ledgered: v1's successful PO delete always 500'd.
**Slice 2c (DONE 2026-08-09, `job-xero-quote` green → 14/40):** quote push
(`documents/quote.py` — expected refusals return typed 400 values with the
provider never called; theme/terms config gates; total-only and breakdown
line modes), provider `create_quote`/`delete_quote`/`download_quote_pdf`
(readonly fabricates `QU-E2E-*` and REFUSES the PDF download — a fabricated
file would satisfy the text assertion against nothing), `POST /api/xero/
create_quote/{job_id}` + `DELETE /api/xero/delete_quote/{job_id}` at
v1-parity fragments (delete takes no id: one quote per job),
`GET /job/jobs/{id}/quote/` serving `{quote: ...|null}` (enveloped — the
generated axios client coerces a bare JSON null body to `{}`; ledgered),
quote PDF inspection (`apps/accounting/services/quote_pdf.py` + the
`inspect_xero_quote_pdf` command whose single JSON line the spec parses),
and the frontend quote workspace: **`features/job/costing/CostLineGrid`**
(the one grid — estimate/actual arrive later as prop configs) carrying the
full day-one selector contract (`.smart-costlines-table`, trailing phantom
row, `SmartCostLinesTable-*`/`DataTable-row-*`/`data-grid-*`,
`ItemSelect-option-*`), JobQuoteTab + XeroQuoteCard. Grid deferrals with
attributes already in place: keyboard-nav behaviour, duplicate-line,
unit-rev override bookkeeping, data-freshness polling. Also still deferred
from the slice-2 plan: reprocess_xero bulk repair, sync-progress UI, seed
command, xero-errors admin endpoints. The earmarked ultrareview over
2a+2b+2c ran and its verified findings landed as PR #49 (the sub-cap
cleanups it declined to block on are in the engineering backlog).

**Xero errors.** `xero_errors_list`, `_retrieve`, `_grouped_retrieve`,
`_grouped_mark_resolved_create`, `_grouped_mark_unresolved_create`.
Models present: `XeroError` · Services none · Router not registered. Admin error views; no spec.

**Xero apps.** **DONE** (xero/foundation slice) — ninja `xero_apps_list`,
`_create`, `_partial_update` (credential change wipes tokens + restarts
workers), `_destroy` (refuses the active row), `_activate`, `_config`;
recorded as renames of v1's `workflow_xero_apps_*` in the parity ledger.
Serves `XeroAppSettings.vue`, which `company-defaults.spec.ts` reaches via
`/admin/company/xero` (frontend page not yet ported).

**Process documents — DEFERRED until after cutover, except safety AI.** Forms,
procedures, JSA, and the categories endpoint are deferred. The four safety-AI
operations are SHOULD before cutover under the AI rule above; they do not pull
the rest of the process-document surface into pre-cutover scope.
Models partial: `Form`, `FormEntry`, `Procedure` (`apps/process/models/`). JSA and SWP
are `document_type` variants rather than separate models —
`Procedure.job` is "required for JSA, null for SWP/SOP" (`procedure.py:72`) —
so the 2 JSA ops are not a third model. **There is no category model**, so
`process_categories_retrieve` is greenfield · Services none · Router not registered.
The 4 safety-ai ops must go through the gateway (ADR 0041).
Only `process_forms_entries_list` is on a spec path, and
`form-entries-page-scroll` seeds itself over the API — so a thin slice of this
group greens a spec while the rest do not.

**App errors.** `app_errors_retrieve`, `_grouped_retrieve`,
`_grouped_mark_resolved_create`, `_grouped_mark_unresolved_create`,
`rest_app_errors_retrieve`.
Models present: `AppError` (`apps/core/models.py:28`), **written from across the codebase** ·
Services none no read or grouping service — the write path is done and the read
path does not exist · Router not registered `apps/core/api.py` exposes `build_id_retrieve`
only (line 86). Serves `AdminErrorView.vue`.

**AI providers (SHOULD before cutover; AI).** `workflow_ai_providers_list`, `_retrieve`, `_create`,
`_partial_update`, `_destroy`, `_set_default_create`.
Models present: `AIProvider` (`apps/ai/models/ai_provider.py:10`) ·
Services partial: `llm_client.py` only · Router not registered. Must route through `apps/ai`
(ADR 0041). Note the local Gemini key lives in an `AIProvider` **row**, not env.

**Session replays.** `session_replay_recordings_list`, `_create`,
`_recording_chunks_create`, `_recording_events_retrieve`,
`_frontend_errors_create`.
Models present: `SessionReplayRecording` + `SessionReplayChunk`
(`apps/diagnostics/models/session_replay.py:14,57`) · Services none · Router not registered.
No spec covers it, and `rrweb` is not in v2's frontend.

**Operations.** `operations_workshop_schedule_retrieve`,
`_recalculate_create`.
Models present: `SchedulerRun`, `AllocationBlock`, `JobProjection`,
`UnscheduledReason` · Services none **there is no scheduling algorithm at all** —
the models are a schema shell · Router **registered** (added with data-versions).
Serves `pages/schedule.vue` (992 lines). No spec covers it; this is the group
whose op count (2) most understates its cost.

**Search events.** `search_events_click_create`.
Models present: `SearchTelemetryEvent`
(`apps/search/models/search_telemetry_event.py:11`) · Services none · Router not registered.
Confirmed nothing writes it — the layer-contract deferral is recorded at
`apps/company/services/company_rest_service.py:597`.

**NotebookLM CRUD (SHOULD before cutover; AI)** (in no previous table; only `_menu_list` was listed, as a
blocker). `workflow_notebook_lm_links_list`, `_retrieve`, `_create`,
`_partial_update`, `_destroy`.
Models present: · Services none · Router not registered. The admin screen behind the navbar menu.

### Do NOT port: the operations nothing calls

Beyond the work list above, v1 exposes operations with **zero call sites in its
own frontend** — the second figure in the table's "still to port" row. They are
dead surface, and porting them is work no spec can ever verify. v1's own ledger
records one (`accounts_token_verify_create`, "referenced only by the generated
client"). Confirm a call site exists before porting anything not grouped above.

## Remaining non-API work

| Item | Notes |
|---|---|
| **Frontend SPA** | The largest remaining item by a wide margin — own section below |
| quote-to-PO | **SHOULD before cutover (AI)** — v1 `purchasing/quote_to_po_service.py`, incl. its inline Gemini client → the gateway |
| Middlewares | AccessLogging, DisallowedHost, **FrontendRedirect** (serves the SPA — needed, not optional), PasswordStrength |
| Ops | Dropbox API sync, deploy scripts |

## The frontend rebuild

Real pages so far: login, `/jobs/create`, and the job detail shell (tab bar +
minimal settings tab; every other tab is a stub). `_authed/kanban.tsx` is still
a placeholder. shadcn/ui is installed (`components.json`, new-york/slate, the
radix-era 2.x CLI — the v4 CLI's presets diverge from what v1's specs assert
on) with dialog + button; add primitives with `npx shadcn@2 add <name>`.
Against that, v1's `pages`, `views` and `components` are what has to be
reproduced — the leverage table below says in which order, and the v1 line
counts beside each are a size signal, not a budget.

### Build order by leverage

Ranked by specs unblocked per unit of work, so the order is derivable rather
than guessed. LOC are v1's, as a size signal — several should shrink.

| Component (v1) | LOC | Specs | Note |
|---|---|---|---|
| ~~`App.vue` + `AppLayout.vue`~~ | 173 | 39 | **DONE** (create-job slice) as `_authed.tsx` + `features/shell/`: auth → company defaults → notebookLM links → data versions, in that order. Still to come: the freshness *subscription* (initial fetch only today) and the `route.meta.allowScroll` body scroll-lock the process-documents and mobile-kanban specs depend on |
| ~~`AppNavbar.vue`~~ | 1177 | 39 | **DONE** as a ~50-line `features/shell/AppNavbar.tsx` — only `AppNavbar-create-job` (gated on `is_office_staff`) and `AppNavbar-logout` exist; menus arrive with the pages that need them |
| ~~`PersonSelectionModal.vue`~~ | 894 | 14 | **DONE** including person edit and archive (job-cluster slice); the phone-ownership conflict UI is the one remaining seam (`features/company/PersonSelectionModal.tsx`) |
| `CreateCompanyModal.vue` | 499 | 22 | Reached from CompanyLookup's create-new branch; blocked on Xero Phase 4 company create. `CompanyLookup-create-new` renders inert until then |
| ~~`CompanyLookup.vue`~~ | 326 | 21 | **DONE** (`features/company/CompanyLookup.tsx`) minus create-new/Ctrl+Enter branches (same Phase 4 block) |
| ~~`PersonSelector.vue`~~ | 393 | 14 | **DONE** — auto-selects the primary person once per company change, like v1 |
| ~~`jobs/create.vue`~~ | 530 | 22 | **DONE**; notes field is a plain textarea until the specs that assert `.ql-editor` bring Quill |
| `DataTable.vue` | 135 | 17 | Owns `[data-row-id]`, `[data-grid-col]`, `DataTable-row-N` — the row/cell contract for timesheets, purchasing and CRM |
| ~~`SmartCostLinesTable.vue`~~ | 1870 | 10 | **Built as `features/job/costing/CostLineGrid.tsx`** (2c) — one grid; all three configs live (quote, estimate, actual). The estimate spec's Tab chain holds in natural DOM order (no custom handler); typed drafts persist on row exit and wear a `Save failed` badge until a retry lands; a draft's untouched unit revenue derives at POST time, never into the draft mid-edit (deriving on the cost commit flipped the controlled unit-rev input under a concurrent override — the cost-entry E2E caught it). On the actual set: timesheet lines fully read-only (subtype is plain text), the picker offers no labour, materials book via stock consume (server creates the line), consumed materials stay repriceable inline (v1 rule) but their item binding is dead — v1 locked stock-line repicks there and v2 extends the lock to adjust rows, because a repick PATCHes a new `stock_id` with no inventory movement and desyncs the ledger. Delivery-receipt lines (`meta.source = 'delivery_receipt'`) are fully locked everywhere (v1 rule — their quantity is purchasing history). Still deferred with attributes in place: duplicate-line, unit-rev override bookkeeping on SERVER rows (a cost edit after a manual rev override re-derives over it), data-freshness polling, the actual tab's approve button/pending badge (endpoint live; consume returns approved lines so no spec renders an unapproved one), the Source column, negative-stock badges, the Actual Summary aside/dialog, Estimate/Quote comparison chips |
| ~~`JobSettingsTab.vue`~~ | 1787 | 10 | **DONE** with `useJobAutosave` (job-cluster slice). Labour Rates card and the price-cap/RDTI/urgent controls remain unbuilt — no spec asserts them |
| ~~`jobs/[id]/(index).vue` + `JobViewTabs.vue`~~ | 882 | 10 | **DONE**: header carries the job-number span, inline name/status/pricing edits on the delta contract, and both print buttons; settings and attachments tabs have content, the rest are stubs |

The critical-path flow, the `sharedEditJobUrl` worker fixture, and the job
detail page (header edits, settings autosave, attachments, print) are built —
**every job-cluster spec is green**, and the kanban cluster is unblocked on
everything except its own board.

**Cheapest greens, independent of that flow — fill-in work, not next work
(bend-first list under Cutover).** `not-found`,
`reports/wip-report`, `reports/job-movement` and `reports/companies` are green
(features/reports + features/crm; the shared pieces they established are
`SummaryCard`, `formatCurrency`/`formatPercentage` in `src/lib/format.ts` —
one formatter, because specs assert cross-page string equality on money).
Still cheap and unstarted: `process-documents/form-entries-page-scroll`
(`FormEntriesView`, `DynamicFormEntry`, `EntriesTable`; seeds itself over the
API — needs the process-forms backend slice first, so its true cost is the
process group's, not the spec's). The remaining two report
specs (`sales-forecast`, `payroll-reconciliation`) only read restore-populated
mirror tables (their "Live Xero" flags were wrong) — they are ordinary
frontend slices and among the cheapest greens available.

Formatting in the backend is a bug — the wire carries numbers and the
frontend formats (ADR 0046, written after `total_spend` shipped as
`f"${...:,.2f}"` and the first consumer rendered `$NaN`). A schema declaring
`str` for a quantity is the review smell.

### v1 → v2 library mapping

Recorded so nobody re-derives it or hand-rolls primitives:

- **v1 is shadcn-vue** (`components.json`, style new-york, baseColor slate,
  lucide) — 3,045 LOC under `components/ui/` across 28 primitives.
  **v2 has no component library at all**; `login.tsx` hand-rolls inline SVG
  icons and a bespoke `features/auth/login.css`.
- shadcn-vue is a port *of* shadcn/ui React, so `npx shadcn add` reproduces the
  same class strings **and the same `data-slot` attributes the specs assert on**
  (and `[data-sonner-toast]`). Same upstream relationship for
  `vaul-vue` → `vaul` and `vue-sonner` → `sonner` (already in v2). **Install the
  primitives; do not write them** — that is 3,045 lines you do not author.
- **Missing deps the tested clusters need:** `lucide-react`,
  `@tanstack/react-table` (v1 uses the vue twin in `DataTable`, `PoLinesTable`),
  `vaul` (three drawers), a date library (v1 uses date-fns + date-fns-tz +
  dayjs + `@internationalized/date`; v2 has none), `quill` (specs assert
  `.ql-editor`), and a drag library that emits a **clone node** — see the gotcha
  register.
- **Needed by no spec, so do not port:** `pdf-vue3` (both print specs stub
  `window.open` and assert `%PDF` bytes — there is no viewer to build),
  `@unovis` (zero consumers in v1's `src/`), `vue-advanced-chat`, `rrweb`.
- **No React equivalent exists** for `@kodeglot/vue-calendar`, which
  `WorkshopTimesheetCalendar.vue` wraps for `timesheet/workshop-my-time-view`.
  That is a rebuild or a spec rewrite — treat it as its own item, not a port.

### Stub the tabs no spec exercises

`JobViewTabs.vue` `v-if`-switches all ten job tabs with **static imports**, so a
faithful port drags in `SafetyWizardModal`, `McpToolDetails`,
`RichTextEditor` (Quill), `CameraModal` and the
Quote/History/QuotingChat/Safety/Pdf tabs — **3,100 LOC that no spec
touches**. Lazy-route them behind stubs rather than porting them.

### The generated client is complete and is the only legal API surface

`frontend/src/api/generated/sdk.gen.ts` exports **one function per backend
operation, 1:1, no gaps**. Three shapes: plain SDK functions, TanStack **option
factories** (`<op>QueryKey` / `<op>Options` / `<op>Mutation` — *not* hooks, so
`useQuery(fooOptions({ path: { id } }))`, the pattern already in
`features/auth/index.ts`), and zod schemas. ADR 0021 plus
`scripts/check-api-boundary.mjs` make it the only permitted API access.

## Porting the E2E suite

v1 has **40 spec files**; the ported count is derived in the table at the top.
Case counts are deliberately not tracked here — a spec is green or it is not,
and a per-file case total told no session anything it acted on.

### What carries over unchanged

- **v1's `data-automation-id` values.** 342 distinct ids, and roughly a fifth
  of v1's selectors bind to them — that fraction ports as-is, as do its
  `getByRole` and `getByText` selectors. The rest are structural or css, and
  they cluster rather than spread: see kanban below.
- **`tests/scripts/`** — DB backup/restore, sequence sync and safety checks are
  database-level. So does the auth fixture's API login
  (`POST /api/accounts/token/` → `access_token` cookie).

### What a spec needs before it can run

The old note said six specs have a proven unported dependency. Measured, that
understates it: **22 of 40 cannot reach their assertions**, because their
fixtures build test data by *driving the UI* rather than seeding over the API.

- **`sharedEditJobUrl` — 13 specs.** Worker-scoped fixture in
  `tests/fixtures/auth.ts:283`. All `job/*` except the two create-job specs,
  plus all 5 kanban.
- **Own job through the UI — 11 specs.** `createTestJob()` /
  `submitJobAndWaitForCreatedJob()` (`tests/fixtures/helpers.ts:418`) click
  `AppNavbar-create-job` → `/jobs/create` → `CompanyLookup-input` (types `ABC`)
  → `PersonSelector-modal-button` → `PersonSelectionModal` →
  `JobCreateView-pricing-method`.
- **Union = 22 specs**, and the critical path underneath them is one flow:
  **navbar → jobs/create → CompanyLookup → PersonSelector/PersonSelectionModal
  → job detail redirect.** Nothing in the job, kanban or timesheet clusters
  moves until that flow works. This is the single highest-leverage item in the
  port.
- **API-seeded — 1 spec.** `process-documents/form-entries-page-scroll` posts to
  `/api/process/forms/incident/` and needs no UI for setup. Cheapest spec in
  the suite.
- **Standalone — everything else** (the rows marked "standalone" in the
  table below; no shared or own-job fixture). `crm/people` +
  `crm/people-archive` setups CREATE a company via Ctrl+Enter →
  `POST /api/companies/create/`, live since the Xero foundation slice —
  they are portable now.

| Spec | Route | Fixture | Live Xero | Selectors |
|---|---|---|---|---|
| `company-defaults` | `/admin/company`, `/admin/company/xero` | standalone | **yes** | mixed |
| `crm/people` | `/crm/people` | standalone | **yes** | ids |
| `crm/people-archive` | `/crm/people` | standalone | **yes** | ids |
| `crm/phone-call-job-link` | `/crm/calls` | own job |  | ids |
| `job/create-job` | `/jobs/create` | own job |  | ids |
| `job/create-job-with-new-company` | `/jobs/create` | own job | **yes** | ids |
| `job/create-estimate-entry` | job estimate tab | own job |  | mixed |
| `job/edit-job-settings` | job settings tab | shared |  | ids |
| `job/job-attachments` | job attachments tab | shared |  | ids |
| `job/job-cost-entry-data` | job actual/finish tabs | shared+own |  | mixed |
| `job/job-header` | job detail header | shared |  | mixed |
| `job/job-xero-invoice` | job → Xero invoice | shared | **yes** | ids |
| `job/job-xero-quote` | job → Xero quote | shared | **yes** | mixed |
| `job/print-delivery-docket` | job print | shared |  | mixed |
| `job/print-workshop-pdf` | job print | shared |  | mixed |
| `kanban/debug-drag-bugs` | `/kanban` | shared |  | structural |
| `kanban/kanban-desktop` | `/kanban` | shared |  | structural |
| `kanban/kanban-drag-vanishing` | `/kanban` | shared |  | structural |
| `kanban/kanban-mobile` | `/kanban` (mobile) | shared |  | structural |
| `kanban/kanban-status-priority` | `/kanban` | shared |  | mixed |
| `not-found` | `/crm/clients` | standalone |  | mixed |
| `process-documents/form-entries-page-scroll` | `/process-documents/forms/incident/{id}` | **API-seeded** |  | mixed |
| `purchasing/create-purchase-order` | PO create | own job |  | ids |
| `purchasing/pickup-address` | `/purchasing/po/create` | standalone |  | mixed |
| `purchasing/po-created-by` | `/purchasing/po` | own PO |  | mixed |
| `purchasing/stock-search` | `/purchasing/stock` | standalone |  | structural |
| `purchasing/supplier-alias-search` | `/crm/companies`, PO create | standalone | **yes** | ids |
| `reports/companies` | `/crm/companies` | standalone |  | mixed |
| `reports/job-movement` | `/reports/job-movement` | standalone |  | ids |
| `reports/payroll-reconciliation` | `/reports/payroll-reconciliation` | standalone |  | mixed |
| `reports/sales-forecast` | `/reports/sales-forecast` | standalone |  | ids |
| `reports/wip-report` | `/reports/wip` | standalone |  | ids |
| `staff/create-staff` | `/admin/staff` | standalone |  | mixed |
| `staff/staff-wage-loading` | `/timesheets/entry` | own job |  | ids |
| `timesheet/create-timesheet-entry` | `/timesheets/daily`, `/entry` | own job |  | ids |
| `timesheet/keyboard-nav` | `/timesheets/entry` | own job |  | mixed |
| `timesheet/performance` | `/timesheets/daily`, `/entry` | standalone |  | mixed |
| `timesheet/urgent-job-defaults` | `/timesheets/daily` | standalone |  | mixed |
| `timesheet/workshop-my-time-view` | `/timesheets/my-time` | own job |  | ids |
| `example` | — | — |  | placeholder, delete on port |

**5 specs touch a live Xero tenant** (`company-defaults` test 3,
`crm/people`×2 setup, `create-job-with-new-company`, plus `job-xero-invoice`
and `job-xero-quote` once their push managers port). Four rows previously
carried a wrong "Live Xero: yes": `sales-forecast`, `payroll-reconciliation`,
`create-timesheet-entry` and `job-cost-entry-data` only read restore-populated
mirror tables (`Invoice`, `XeroPaySlip`, `XeroPayItem`) whose backends exist —
they are ordinary frontend slices. One seed constant gates the shared-fixture
specs: `TEST_COMPANY_NAME = 'ABC Carpet Cleaning TEST IGNORE'` (`helpers.ts:7`);
the shared-job fixture also types `ABC` into company lookup.

### The v2 harness: what exists and what is still missing

The three prerequisites landed with the create-job slice and every spec now
runs under them:

- **Console-error guard is ON** (`tests/e2e/fixtures/auth.ts`): any unexpected
  browser `console.error` or `pageerror` fails the test unless whitelisted via
  `test.use({ expectedConsoleErrors: [...] })`. The login-401 allowance lives
  in `tests/e2e/fixtures/authConsoleErrors.ts` (with the fixtures, not app
  source — v2's app never needed the module). A ported spec that deliberately
  triggers errors must bring its whitelist; TanStack Query error logging and
  React error boundaries must toast, not log, or their specs fail.
- **DB lifecycle is ON** (`tests/scripts/global-setup.ts` / `global-teardown.ts`
  / `db-backup-utils.ts`): pg_dump before the suite to `restore/e2e/`,
  single-transaction restore + integrity check + sequence sync + safety check
  after, PID lock in `os.tmpdir()`, stale-lock refusal. Creds come from the
  root `.env` `DB_*` keys, so it backs up whatever database the backend uses.
  Sequence sync required a new backend command, `manage.py sync_sequences`
  (`apps/core/management/commands/`).

The Xero lifecycle pieces are ON: the ping preflight
fails setup closed on not-connected, on a backend not reporting
`xero_readonly`, and on production-client-with-writes; teardown saves the
active XeroApp token before restore and re-injects it after (Xero rotates
refresh tokens — the row in the backup is already dead), with the 90s settle
wait before restore. Still missing: **sync-window open/close** (seam comment
atop `global-setup.ts`) — only consumed by the slice-2 sync loop. Kanban waits
only on its own board. (v1's rich login diagnostics are debugging aids, not
blockers; port them if a flaky login ever needs them.)

Runtime prerequisite for any run: the dev DB's active `workflow_xeroapp` row
must hold the CURRENT token rotation. If another environment (e.g. v1 dev)
refreshed last, Xero answers `invalid_grant: Refresh token has been consumed`
— copy the token columns from whichever DB refreshed most recently, or redo
the OAuth flow via `/api/xero/authenticate/` (needs the registered ngrok
callback domain).

The v1 **`e2e_cleanup` / `test:e2e:reset`** recovery path is now ported: transactional deletion
ordered around the accounting/purchasing PROTECT edges (invoice/quote by job AND company, POs by
supplier), a loud refusal when a matched company carries quoting scraper data or is the shop
company (those names mean production data), sequence sync, clean-backup rotation and stale-lock
recovery. `scripts/ops/run_e2e.sh` composes it with a fresh five-service stack and owned-process
teardown for unattended agent runs.

The config keeps `fullyParallel: false`, `workers: 1`, `maxFailures: 1`,
`timeout: 120000`, `actionTimeout: 0`, `trace: 'on'`. The suite is serial by
design, so **raise `maxFailures` on the CLI when triaging**
(`--max-failures=10`) — at 1 it hides every other failure behind the first,
and **11 specs use `test.describe.serial`**, so one early failure also skips
the rest of its own file.

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

## Post-cutover — decided, deliberately NOT before 15 August

Each of these has an answer already; none blocks an E2E spec, so none earns a
day before the date. Recorded here because a decision that lives only in a
session task list is a decision that gets re-litigated.

1. **A client error IS an AppError — invert the rule.** Decided 2026-08-07.
   422s already persist; the change is that service-level client errors must
   too. `PhoneCallRecord` is append-only — nothing in `apps/` deletes one — so
   "Phone call not found" for a well-formed id can only be a client bug, id
   probing, or an id from another environment. No benign fourth case. Work: the
   12 assertions across 6 files requiring `AppError.objects.count() == before`
   invert, `TestClientErrorsDoNotPersistAppErrors` gets renamed, and ADR 0019
   records the reasoning. Do 2 with or before this — it is what makes the
   volume real.
2. **AppError retention: 90 days resolved, 365 unresolved.** Decided
   2026-08-07. Nothing deletes an AppError today: no beat task, no management
   command, no admin action. `persist_app_error` dedupes per exception
   *instance* ("one failure is one row"), so each request costs a row, and the
   size driver is the `data` JSONField holding a full traceback. Production
   volume is unmeasured — the DB user lacks permission on `workflow_apperror`.
3. **WIP report: bound invoices by the report date, and stop dropping unbilled
   jobs from the cost view.** Decided 2026-08-07. Deliberately post-cutover:
   **both halves change reported numbers on the day they ship**, and moving a
   figure people reconcile against during a cutover weekend is how a real
   problem gets blamed on the wrong thing. Needs a behaviour-ledger entry and
   someone telling whoever reads the report.
4. **Response nullability, which shrinks per slice rather than in a sweep.**
   The count is in `docs/code-quality.md` under *Wire contract*, derived from
   the exported schema. Presence is already settled: optional response
   properties are pinned at zero by `export_openapi`, because ninja sends every
   declared field and a client should never branch on absence. Nullability is
   what remains, and it is not a number to drive to zero — `| None` is often
   correct. **When a slice ports a screen, the response schemas that screen
   reads declare `| None` only where the producing service can actually return
   `None`.** The service code is open at that moment, so the judgment costs
   minutes; batched into a sweep it costs days and blocks no spec.

   The figure this replaces said "~72 properties". It was the count of
   `nullable` response rows in the deleted v1-parity baseline — a measure of
   where v1 happened to be stricter, never a v2 number. It is derived now so
   that cannot recur.
5. **Single-source the numbers in this file.** Prose still restates figures the
   derived table owns, which is exactly what went stale twice.
6. **Purge "v1" and "v2" from everything: comments, docstrings, docs, ADRs,
   filenames.** The words are banned once the port is over. **We document
   state, not change.**

   The test: someone opens Docketworks for the first time and does not care how
   the code came to be like it is. They care what it does and what it means
   now. So a comment saying "v1 silently substituted the company default; v2
   raises" becomes "a staff member without a wage rate cannot be costed" — the
   invariant, stated in the present. "In Docketworks you cannot have a system
   without a row in `CompanyDefaults`" is the shape to aim for: a fact about
   the system, carrying no archaeology.

   Scope is wide, so budget for it rather than discovering it: this file, the
   cutover checklist, every ADR carrying "ported from" reasoning, the behaviour
   ledger (whose every entry is framed as a difference from something that no
   longer exists), the `db_table = "workflow_*"` overrides and their
   explanations, `scripts/v1-frontend-operations.yml` and its generator,
   `export_openapi.py`'s `DISSOLVED_V1_APPS`, and the port-progress rows in
   `status_table.py`. Much of it does not need rewording — it needs deleting,
   because it only ever described a transition. **Delete first, reword only
   what states a live invariant.**

## Engineering backlog (no decision needed, just work)

1. Port v1's kanban search-ranking test net (~30 tests). The scoring code is
   line-identical to v1 but the regression net is thin (4 tests).
2. CRM wire-pin tests (portal login/CDR form fields, `b"200"` strip,
   `Result == "1"`, timeouts) and superuser-gate tests on recording deletes and
   endpoint CRUD.
3. Hoist connection hygiene (`close_old_connections` guarded by
   `in_atomic_block`) into `apps/core`: four copies exist and
   `apps/crm/tasks.py` still has two unguarded calls.
4. Unify invalid-state handling across document managers: the quote manager
   refuses expected business states with readable 400 values, but the invoice
   sibling still raises `ValueError` for "job already paid" (a 500 via the
   envelope). The quote slice introduced the better pattern; the fix belongs
   on the invoice side (`invoice.py` `state_valid_for_xero` call site).
   Include the provider while there: `create_invoice`/`delete_invoice`
   should adopt the quote/PO `summarize_errors=False` + element
   `validation_errors` pattern instead of relying on the endpoint family's
   default whole-request 400.
5. Split `apps/xero` by capability — routers and provider modules for
   connection, contacts, sales documents, purchasing, sync — keeping
   invoice/quote/PO domain orchestration separate. `api.py` is ~1,200 lines
   and `provider.py` ~600; the shared document-endpoint adapter (landed with
   the quote hardening) stops the scaffolding drift, but the file split is
   deliberate post-cutover structure work.
6. Ultrareview sub-cap cleanups from the quote slice: managers read
   provider-private `_sub_total`/`_total` raw keys the readonly provider
   must fabricate; `EMPTY_SERVER_SHAPE` could be a `Pick<CostLineOut, ...>`;
   XeroQuoteCard/JobInvoiceCard are siblings with drift; the item picker's
   stock search fires per keystroke undebounced; the quote tab duplicates
   the HOURS formatter; a dead "No online URL" toast.
5. Root `conftest.py` guard failing any test that attempts a real network call.
   `LLM_BOUNDARY` is module-bound, so a second consumer of `chat_completion`
   silently patches nothing.
6. **SHOULD before cutover (AI): no timeout, retry or spend cap at the LLM boundary.** litellm's default
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
   behaviour, and **one of v1's 40 specs is ported** — so by the rule
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
18. Timesheet-entry review leftovers (both inherited shapes, neither spec-
   asserted): a draft's stale `labour_subtype` surviving a job repick can
   make `rateForSubtype` throw in the bill cell's render when the new job
   lacks that rate row — clearing the subtype on repick is the fix, but v1
   misbehaves here too (handler throw), so the unified behaviour needs a
   decision; and `SmartTimesheetTable`'s focus handoff queries `document`
   rather than the grid's root, which breaks silently if two grids ever
   mount on one page.

## v1 defects found by this rewrite

Recorded because they are live in production, not just porting notes. Full
detail in the parity ledger.

- **KAN-329** — blank `item_code` on a PO line trips its own CHECK constraint
  (409, price change rolled back). Fixed in v1 (PR #525).
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
- **Estimate and quote quantity edits moved real inventory** — v1's
  cost-line update view diff-adjusted the linked Stock row on every quantity
  change and its delete view returned the quantity, with no cost-set-kind
  guard, so editing an estimate line 1→10 drew 9 units of stock nothing
  consumed. v2 guards both movements on `cost_set.kind == "actual"`
  (ledgered); v1 unfixed. Found by the cost-entry spec's estimate scenario.
