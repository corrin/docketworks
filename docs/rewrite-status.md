# Rewrite status — what remains and what needs a decision

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

Last updated: 2026-08-16 NZ. The v1 operational port is complete
(`v1-disposition.md` is the inventory; the restore-prod-to-nonprod runbook was
executed mechanically from the v2 docs as its acceptance test), and this file
was rebuilt to work-to-come only: completed-slice narratives are deleted,
frontend architecture contracts moved to
`frontend/docs/architecture-contracts.md`, environment facts to
`docs/development_session.md` and `docs/xero_setup.md`.

## Cutover: Saturday 22 August 2026

**Ruled 2026-08-14: the 15 August window was declined and cutover moved one
week to 22–23 August.** At decision time MUST-tier specs were still red —
among them `/timesheets/weekly` (declared MUST that same day, unstarted),
`workshop-my-time-view` (calendar rebuild), `staff/create-staff`,
`company-defaults`, the CRM people pair, `pickup-address` and the unconfirmed
`supplier-alias-search` — and the rehearsal items in the milestone below were
open, so gate 1 could not pass inside the window. The gate questions, the
2026-08-14 tiering and the stay-on-v1 fallback carry forward unchanged:
deferral moves the date, never the definition of done. Scope is frozen as
tiered 2026-08-14 — nothing new enters MUST. **Checkpoint Wednesday 19
August:** count MUST specs green; if the trajectory misses, the go/no-go call
is made then, not on the night.

**The date is immovable; scope bends.** The date exists to stop the project
spinning on work that serves neither of the two questions actually asked at
go/no-go — lint-level and type-level polish past what either criterion
below needs is exactly that kind of spin, and is what the date is for
cutting off. It is not license to weaken either criterion: the honest
fallback if either fails is **abort and stay on v1**, not ship anyway — v1
already works, so declining to cut over is always a safe outcome, and there
is never a scenario where shipping worse architecture is the safer choice.

**Go/no-go is decided by two independent questions, either of which is
grounds to reject:**

1. **Does this replicate all the functionality the business needs?**
   MUST-tier E2E specs green is the measurable proxy for this; a red MUST
   spec means no release.
2. **Is this materially better architecture and code — enough to justify
   the move?** Not proxied by any single gate; judged directly. Racing bad
   architecture into production defeats the point of the rewrite (v1
   already proves the functionality works; the rewrite's only reason to
   exist is the architecture).

Both must pass. Release that weekend if they do.

### Materially-better architecture: exit criteria

This is the work that can still change the architecture verdict. It is not a
general cleanup list: each item below either closes a measured structural hole
or makes the release evidence trustworthy.

- [ ] **Restore the cross-cutting controls v1 has and v2 still lacks:**
      `FrontendRedirect`, `AccessLogging`, `DisallowedHost` and the complete
      weak-password path. The password work includes validation, an
      authenticated password-change API and UI, and enforcement of
      `password_needs_reset`; returning the flag from login while the frontend
      ignores it is not a security control. Forgotten-password email remains
      the separate `blocked-by:email-feature` slice.
- [ ] **Make the one-implementation rule cover the whole application.** Run
      the existing Python gate over `apps/`, extend it with an equivalent
      TypeScript/React check over `frontend/src/`, hoist the four Celery
      connection-hygiene copies into `apps/core`, and add a root test guard
      that fails any unmarked real network call. These are known holes in ADR
      0039 and the hermetic unit-suite claim, not optional polish.
- [ ] **Return the project to its permanent repository identity.** On switch
      day, archive v1 privately, replace `corrin/docketworks` with this history,
      and make `https://github.com/corrin/docketworks` the canonical remote.
      Then update local clones, server mirrors, CI/secrets, badges and literal
      `_v2` URLs. Follow the ordered, rollback-conscious procedure in
      `docs/cutover-checklist.md`; a GitHub redirect is a transition aid, not
      the permanent configuration.
- [ ] **Bring every handwritten code file back under 500 lines.** The
      2026-08-16 baseline is 42 production files and 21 test files over that
      threshold after excluding generated API clients and migrations; the
      largest production files are
      `apps/job/services/job_service.py` (2,837), `apps/job/api.py` (1,810) and
      `apps/job/services/workshop_pdf_service.py` (1,582). Execute in four
      bounded passes: (1) add a generated inventory and CI gate with no new
      over-limit files or increases; (2) split every production file over
      1,000 lines; (3) split the remaining production files; (4) split the 21
      test files by behaviour under test. The final count is zero. Generated
      files remain exempt because their source schema, not their emitted
      layout, is the maintainable unit.
- [ ] **Ship an honest release surface.** Every route linked from navigation
      works, every implemented release route is reachable through navigation,
      and visible job tabs do not lead to a later-slice placeholder. A deferred
      capability is hidden, not presented as an inert control.
- [ ] **Prove one immutable release candidate.** Record the candidate SHA and
      run CI, the unit suites, all MUST E2E specs, live-provider integration
      tests, restored-production smoke tests, and the UAT cutover/rollback
      rehearsal against that SHA. Any subsequent code change invalidates the
      evidence and produces a new candidate.
- [ ] **Make this file truthful at the candidate SHA.** Remove completed work
      immediately, reconcile every `blocked-by:` disposition whose feature has
      landed, and check the remaining feature descriptions against the actual
      routers and routes. Generated counts prevent arithmetic drift; this
      semantic pass prevents stale prose from directing the final week.

Line count identifies where decomposition is required; it does not prescribe
the decomposition. Each split must leave one implementation per concept and a
clear capability owner. Moving arbitrary line ranges into vaguely named helper
modules would satisfy the number while preserving the architectural defect.

### Delivery tiers

| Tier | Meaning | Scheduling rule |
|---|---|---|
| **MUST before cutover** | The release is unsafe or unusable without it | Release-blocking; always the next work while any MUST item is open |
| **SHOULD before cutover** | Valuable pre-cutover scope that is not required for a safe release | Pick up only when it cannot put the MUST milestone at risk |
| **DEFERRED until after cutover** | Explicitly outside the cutover scope | Do not pick up before release; ships spec-first when picked up |

**Every DEFERRED screen ships spec-first (decided 2026-08-14).** A deferred
slice includes an E2E spec — freshly authored, since most of these screens have
no v1 spec to port — and the slice is done only when that spec is green. The
spec is written with the slice, not before cutover (explicit user choice: no
pre-flip hours on specs for unbuilt screens). Deferral moves a screen's date,
never its definition of done.

**The admin tail is SHOULD-plus (decided 2026-08-14): really painful to
slip.** Labour-rates, archive-jobs, the month-end UI (backend done, accounting
slice) and the AppError viewer (write path done everywhere; the read/grouping
API and page are unbuilt) are the first work after the MUST milestone, and the
first week's work if they slip. None has a spec; each slice authors its own.

**AI is SHOULD before cutover, not MUST.** This includes quote chat, safety AI,
AI-provider administration, NotebookLM CRUD, the quote-to-PO AI path, and the
production-safety work at the shared LLM gateway. Existing boot plumbing under
`/api/ai/` is already done and remains part of the application shell; this tier
controls the unfinished AI product work.

**Deferred (decided 2026-08-09, revised 2026-08-14):**

- **Reports slip ~one week post-cutover** — every remaining report screen:
  the `sales-forecast` and `payroll-reconciliation` specs (v1 specs exist and
  port), the no-spec job-reports group, and the ten no-spec report screens in
  the pre-scoped table below (each authors a fresh spec with its slice).
- **Process documents** stay deferred, except the four safety-AI operations
  (SHOULD, AI rule above); `process-documents/form-entries-page-scroll` goes
  green with the process-forms slice.
- **`/purchasing/mappings` (scraper-to-DB matching) slips ~one week.** The
  purchasing MUST is the ability to make purchase orders, which the four green
  purchasing specs plus `pickup-address` cover. Fresh spec with the slice.
- **Price-list extraction** is its own deferred slice (see pre-scoped table);
  v1's `/purchasing/pricing` page is NOT the slice — see the do-not-port note.
- **Schedule (`/schedule`) slips, realistically by more than a week** — no
  scheduling algorithm exists in either repo's backend port (the v2 models are
  a schema shell), so the slice is algorithm + page + fresh spec.

The `example` spec is a placeholder to delete, not release scope.
Every other spec in the E2E table is MUST unless this section explicitly moves
it to another tier.

### Milestone: all MUST tasks complete

- [ ] Every MUST-tier E2E spec is green.
- [ ] Every backend and frontend slice required by those specs is complete.
- [ ] `/timesheets/weekly` — page, payroll write side and spec are built, and
      the payroll write is proven by tests that perform it: `weekly-payroll`
      seeds hours in the postable week, posts through the panel, and reads Xero
      back through `GET /api/timesheets/payroll/week-status/`, and
      `apps/xero/tests/test_payroll_integration.py` covers the same path plus
      all four Docketworks leave types against the demo tenant. Its single
      repeatable lifecycle posts, changes and re-posts, restores and re-posts,
      then repeats unchanged to prove Xero replaces rather than accumulates.
      Nothing here is asserted from a fake provider or a manual check.
      The whole cluster has to be green together: the spec runs in
      `./scripts/ops/run_e2e.sh`, the integration suite in
      `./scripts/ops/run_integration_tests.sh`, and neither runs in CI, so
      running them is the gate.
- [ ] The production-serving path is complete, including `FrontendRedirect`
      and deployment scripts. The server suite lives at `scripts/server/`
      (host convergence, instance lifecycle, immutable releases,
      deploy/rollback/backups, UFW + fail2ban, the ASGI serving model in the
      gunicorn template per ADR 0047, per-instance Redis broker databases),
      with v1-to-v2 host-migration helpers at `scripts/server/cutover/` and
      the operator guide at `docs/server_setup.md`. Remaining before this
      checks: disposable-host double-run and the UAT cutover rehearsal
      (`scripts/server/cutover/README.md` prerequisites, including a
      `production` branch in this repo for prod's tracked ref).
- [ ] Every unchecked release-gate, data-prerequisite, migration, environment,
      and live-integration item in `docs/cutover-checklist.md` is complete.

**This milestone is the go/no-go gate.** SHOULD work is still targeted before
22 August, but an incomplete SHOULD item does not hold the release and never
displaces an open MUST item. DEFERRED work starts only after cutover.

### Deferred slices, pre-scoped (2026-08-14)

Frozen facts about v1 plus the measured v2 backend state, recorded so no
future session re-derives them. LOC are v1's — size signals, not budgets.

**Report screens.** Ten of twelve are frontend-only against a done backend;
only two need backend work. No charting library anywhere in v1 — every screen
is cards plus hand-rolled tables, so porting is layout plus typed fetch.

| Screen | v1 page (LOC) | Operations | v2 backend |
|---|---|---|---|
| job-aging | `reports/job-aging.vue` (475) | `accounting_reports_job_aging_retrieve` | done |
| job-profitability | `reports/job-profitability.vue` (760) | `job_profitability_report` | **missing** (job-reports group) |
| kpi | `reports/kpi.vue` (498) + `components/kpi/` (~1794) | `accounting_reports_calendar_retrieve` | done |
| rdti-spend | `reports/rdti-spend.vue` (432) | `accounting_reports_rdti_spend_retrieve` | done |
| sales-forecast | `reports/sales-forecast.vue` (782) | `sales_forecast_list`, `sales_forecast_month_detail` | done |
| sales-pipeline | `reports/sales-pipeline.vue` (1225) | `accounting_reports_sales_pipeline_retrieve` | done |
| staff-performance | `reports/staff-performance.vue` (394) | `accounting_reports_staff_performance_summary_retrieve`, `_staff_performance_retrieve` | done |
| payroll-reconciliation | `reports/payroll-reconciliation.vue` (358) | `accounting_reports_payroll_date_range_retrieve`, `_payroll_reconciliation_retrieve` | done |
| profit-and-loss | `reports/profit-and-loss.vue` (764) | `accounting_reports_profit_and_loss_retrieve` | done |
| data-quality/archived-jobs | `reports/data-quality/archived-jobs.vue` (448) | `check_archived_jobs_compliance` | **missing** (job-reports group) |
| data-quality/duplicate-phones | `reports/data-quality/duplicate-phones.vue` (264) | `check_duplicate_phones` | done |
| data-quality/duplicate-identities | `reports/data-quality/duplicate-identities.vue` (245) | `check_duplicate_identities` | done |

Sizing notes: kpi is the largest slice (~2,300 LOC total — the page is small
but the `components/kpi/` calendar-and-modals tree is not). sales-pipeline's
1,225 LOC is inflated by an inline `h()` render-function table (~700 lines)
that converts to plain JSX; real complexity is lower than the count suggests.
Only sales-forecast and payroll-reconciliation have v1 specs to port; the
other ten author fresh specs with their slices.

**Purchasing mappings.** Backend done and codegen'd:
`listProductMappings` / `validateProductMapping`
(`apps/purchasing/api.py:839,858`, `services/supplier_pricing_service.py`).
The slice is one route plus one page in the `StockPage.tsx`/`PoListPage.tsx`
shape (v1's `purchasing/mappings.vue` is 388 LOC, no child components, edits
in a modal — no editable grid, no pagination) plus a fresh spec.

**Price-list extraction.** The business purpose: upload a PDF of supplier
pricing for a supplier without a scraper, have AI analyse it, and surface the
results on the mappings screen — the manual-supplier twin of the scraper
path. The seam note atop `apps/quoting/services/price_extraction.py` is the
scope record (~1,300 v1 LOC not ported; two vendor SDKs v2 bans at feature
level). The slice routes through the LLM gateway (ADR 0041), arbitrates the
duplicate-detection conflict the seam note flags, and rebuilds the
`/purchasing/pricing` screen with a WORKING upload (v1's page never had one —
see the do-not-port note).

Ordering and spec ownership between the two purchasing slices: **the mappings
slice lands first** and its spec covers the screen over scraper-sourced data
(browse, filter, validate). The extraction slice depends on that built screen
and its spec owns the cross-screen flow — upload a PDF, extraction runs, the
new mapping appears on the mappings screen. One flow, one owner; the mappings
spec does not assert anything about uploads.

**Schedule.** `pages/schedule.vue` (992 LOC) over a backend with no
scheduling algorithm — `apps/operations` models are a schema shell. Algorithm
plus page plus fresh spec; the largest deferred slice by a wide margin.

**Read-side fallback cleanup ([KAN-338](https://docketworks.atlassian.net/browse/KAN-338)).**
The settings and typed-model layers carry no fallbacks, but ~40 reads of our
own JSON shapes violate ADR 0015/0028/0045, concentrated in JSONField payloads
mypy cannot see into. KAN-338 carries the site list and prescribed fixes.
Spec-first like every deferred slice; the `is_billable` divergence between
timesheet aggregation and the shop-job validator is the priority — it is
billing math that can already disagree on real rows.

**Overtime repair pricing
([KAN-339](https://docketworks.atlassian.net/browse/KAN-339)).** The OT
repair commands (`create_overtime_entries`, `reclassify_overtime_entries`)
price 1.5x/2x pay-item lines at the base wage — a preserved v1 defect, ruled
ticket-not-fix 2026-08-15. The ticket carries the prescribed fix (route
through `apps/job/services/time_entry_rates.py`) and the
historical-row question.

**Scrubber policy: exactly PII, exactly once
([KAN-340](https://docketworks.atlassian.net/browse/KAN-340) +
[KAN-341](https://docketworks.atlassian.net/browse/KAN-341)).** The ruling
(ADR 0039: responsibilities are exclusive): the production-host scrub is the single confidentiality
transition and removes exactly PII — no more, no less; downstream data is
non-confidential by construction and is never re-scrubbed. KAN-340 carries
the adjudications of inherited over-aggressive behaviours (unlinked-delete of
non-PII rows, the truncation list, fake-name consistency); KAN-341 carries
the mechanism — a field inventory with an explicit scrub/keep ruling per text
field and a completeness gate over ALL apps, generalising the CRM-only pin so
the next PII field outside the hand-scoped models cannot pass tests unruled
(the pay-slip leak lived in exactly that blind spot).

**Each deferred slice is planned in the session that picks it up, with this
table as its starting input.** Nothing beyond this table is designed before
then — a design made against today's codebase rots before the slice runs, and
the facts above are the ones that cannot. Schedule additionally needs a
scoping pass of v1's scheduling backend (the
`operations_workshop_schedule_retrieve` / `_recalculate_create`
implementations in `../docketworks`) at pick-up time, since the v2 backend is
a schema shell.

## Where things stand

| Measure | Value |
|---|---|
| E2E specs ported | **32 of 40** — green is the only measure that counts |
| Backend operations still to port | **71** (see below; 32 more exist but nothing calls them) |
| API operations v2 exposes | 216 (`frontend/schema.v2.yml`, kept fresh by its own gate) |
| Unit tests | 2227 (all passing) |
| Coverage | above the 88.4 fail_under floor (coverage's own gate on CI's pytest --cov run; ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, every suppression counted in [`code-quality.md`](code-quality.md), all gates on every commit |
| Behaviour ledger | 103 recorded deviations |
| ADRs | 38 (v1's 26 carried forward + 0038–0041, 0043, 0045–0051 written here) |

**Written is not ported.** Every operation in `apps/` is unexercised end to end,
so by rule 1 above none is done. Report progress as specs green; a count of
endpoints written measures typing, not delivery.

**`find_duplicates.py` has never been pointed at a frontend.** v1's carries the
same pathology it was built to catch — three company-defaults services in one
directory under three naming conventions. Run it over `frontend/src/` as that
tree grows, or the rewrite reproduces exactly what it was meant to escape.

## Gotchas — read before picking up a slice, not after

Each of these is invisible until it costs a day, and each was measured rather
than guessed. Details sit with the slice that owns them; this is the index.

1. **22 of the 40 specs cannot reach their assertions until one UI flow works.**
   Their fixtures build test data by *driving the browser* —
   `AppNavbar-create-job` → `/jobs/create` → `CompanyLookup` →
   `PersonSelectionModal` → submit. Not by seeding over the API. (That flow is
   built; the constraint remains for any spec whose fixture drives it.)
2. **`company-defaults` blocks far more than its own spec.** `JobViewTabs`
   renders `JobEstimateTab` only under `v-if="companyDefaults"`, so the whole
   job cluster is dark until it exists.
3. **Every `console.error` fails a test.** The guard is ON in v2's fixture
   (`tests/e2e/fixtures/auth.ts`): any unexpected browser console error or
   uncaught page exception fails the test. New code must route TanStack Query
   error logging and React error boundaries to toasts, or bring a per-spec
   whitelist (`test.use({ expectedConsoleErrors: [...] })`).
4. **`[data-is-clone]` was a sortablejs artefact** in v1's two drag specs. The
   board runs on pragmatic-drag-and-drop, which produces no clone node, so
   those assertions did not port — confirmed dropped, not skipped. The
   stuck-class checks that DO remain (`sortable-chosen` etc.) are absence
   assertions that pass trivially under pragmatic.
5. **`@kodeglot/vue-calendar` has no React equivalent.** It backs
   `workshop-my-time-view`. Rebuild or rewrite the spec; it is not a port.
6. **`timesheet/performance.spec.ts` asserts wall-clock budgets** — a query
   waterfall fails it even when the page is correct.
7. **`getPhantomRowIndex()` (`helpers.ts:228`) requires a trailing empty row**
   in `SmartTimesheetTable`, discovered via `DataTable-row-N`.
8. **5 specs touch a live Xero tenant** (see the E2E table — four rows once
   said "yes" wrongly; they only read restore-populated mirror tables). The
   teardown waits `PRE_RESTORE_XERO_SETTLE_MS = 90_000` before restoring.
9. **Generated types are camelCase** (`user.fullName`). v1's snake_case field
   access does not transfer, and the generated TanStack exports are *option
   factories*, not hooks.
10. **`maxFailures: 1` plus 11 `test.describe.serial` files** means one early
    failure hides most of the suite twice over. Raise it when triaging.
11. **Only two kinds of number belong in this file, because it is throwaway.**
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
    how much. `Coverage` is no exception any more: the row states the
    `fail_under` floor from pyproject (derived), and the ratchet is coverage's
    own gate on CI's `pytest --cov` run — the measured percentage is stored
    nowhere, because a stored measurement was the one number a passing local
    check could not verify.

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
   Your call whether cost-line writes gate on office/superuser (or
   ownership) before or after cutover.

1. **WIP report "as at" semantics (CodeRabbit, PR #22).** For a historical
   `date=` the cost side is bounded by the report date but the invoiced
   amount is not (v1 identical), so invoices issued after the report date
   reduce historical net WIP. Likewise the `total_rev == 0` inclusion gate
   drops cost-only jobs from the `method=cost` view (v1 identical). Both are
   faithful ports whose "fix" changes report numbers — your call whether v2
   should bound invoices by date / gate on the selected method. Declined in
   the PR threads pending your decision.

Settled and binding, so do not re-litigate: `parser_version` is the re-parse
marker, and an operator's hand-validation outranks the parser — never overwrite
a validated mapping.

### Cross-report divergences (recorded 2026-08-04, accounting slice)

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
  awaiting_approval counts twice); the sales pipeline counts each JOB once.
  "Quotes submitted this month" differs between the two screens. Only the
  counting rule is still open — both reports now take their window from
  `apps/accounting/services/report_windows.py`, so period bounds no longer
  differ.
- **Team billable %**: staff-performance uses the unweighted mean of
  per-staff percentages and includes shop revenue in `total_revenue` while
  excluding shop hours from `billable_hours`; the timesheet screens use
  weighted total-over-total. Same person, different utilisation number.
- **Payroll hours source**: `payroll_reconciliation_service` reads
  `XeroPaySlip.timesheet_hours + leave_hours` (model fields); v1's deferred
  `xero_hours.py` twin parses `raw_json` and hardcodes its window — the
  ported `apps/timesheet/services/xero_hours.py` must not bring the
  divergence into the reconciliation report.
- **Reconciling payroll should not wait for a sync (planned).** The report
  compares against `XeroPaySlip`, which Xero only produces once the pay run is
  Posted and the sync has mirrored it, so it cannot answer at the moment an
  operator posts — when the mistake is still cheap to fix. The live read added
  for the weekly panel (`week_posting_status`, draft timesheets plus the leave
  API) answers immediately and needs no mirror, and generalising it from one
  week to a date range is what replaces the sync-dependent half.
  Two constraints shape that work: **gross pay stays slip-sourced**, because a
  timesheet line carries units and not dollars, so the money comparison still
  needs a Posted run; and the live read costs one Xero call per staff per week
  with no bulk leave endpoint, so it belongs behind an explicit trigger rather
  than a page load.
  Two defects to fix in the same slice: `_jm_week` keys staff by DISPLAY NAME,
  so two people sharing one merge into a single row; and `xero_hours` derives
  leave from job names (`LEAVE_JOB_NAMES`) rather than the line's pay item,
  which ADR 0007 records as the v1 mistake that let three leave rules drift.

  **The report's core value is the employee nobody posted for.** Xero pays an
  employee it holds on the calendar their pay-template hours — typically a full
  40-hour week — when the pay run contains no timesheet for them. ADR 0007
  already handles the known case by posting an empty timesheet for a staff
  member with no hours; the dangerous case is an employee DocketWorks never
  lists at all: no `Staff` row, no `xero_user_id`, or a `date_left` that passed
  while Xero was never told. Every one of those is paid a week they did not
  work, and no amount of comparing the staff the app knows will surface it.
  So the reconciliation must be driven from **Xero's** employee list, not the
  app's: `payroll_employees.get_employees()` already pages it to exhaustion,
  and `existing_timesheets_for_week` already returns the posted employee ids,
  so the at-risk set is the difference. Two facts are still missing before that
  difference is trustworthy, and both are per-employee reads: whether the
  employee is assigned to THIS payroll calendar (only those enter the run) and
  whether they are terminated. Until it exists, `week_posting_status` compares
  only the staff DocketWorks lists, and the panel says so rather than implying
  Xero has been checked whole.

Also recorded: v1's `format_period_label` was dead code with zero call
sites — not ported.

## Data-migration path

The rules and the guard live with the code:
`config/tests/test_data_migration_script.py` fails if a new data-writing
migration ships unclassified (seeding migrations collide with the restored
rows and must be cleared first; row-fixing migrations run against an empty
database and must re-apply after the restore — both handled in
`scripts/ops/migrate_v1_data.sh`).

Still-live facts for cutover:

- **v1 PR #522 is deployed (2026-08-07)** — every dump taken before that date
  carries the 31 repaired rows, so take a fresh dump for cutover and rebuild
  the rehearsal database from it. (The 2026-08-15 restore used a fresh dump;
  `docketworks_v2` is current again.)
- **When validation rejects long-standing production data, suspect the model
  first**, and **test any destructive predicate against real data first** —
  of 63 rows flagged in the 2026-08-04 scan, 32 were the model's own
  contract being stricter than its column, and one "junk" blank PO line held
  $119.50 of received stock.
- **Measure the database the claim is about** — the quoting/0002 "harmless"
  misclassification came from measuring an already-normalised database
  instead of a restore built the way cutover builds one.

## Measured risk: the sitemap shard

The scraper reads `sitemap_0.xml` only (v1 did too — inherited). If the
catalogue ever spans a second shard, those products become invisible AND get
retired by the discontinue sweep. Measured 2026-08-01: 3,677 distinct product
URLs against a 50,000-per-shard limit — ample headroom; a monitoring concern,
not a live bug. The pre-cutover live-portal run should confirm the shard
count. Defence in place: the sweep refuses (and persists an AppError naming
the counts) when the sitemap lists under 50% of the LIVE catalogue
(`MIN_SITEMAP_COVERAGE`) — the shard-loss signature trips it instead of
mass-retiring.

## Remaining backend work

The count is in the table above and is **derived, not typed**: v1's operation
surface is frozen in `scripts/v1-frontend-operations.yml`, and
`scripts/checks/status_table.py` subtracts the live `frontend/schema.v2.yml`
from it. Porting an operation lowers the number with no edit to any file, and
`--check` fails if the table or a sentence disagrees.

That file is a **work list, not a contract authority**. It records which
operation names v1's frontend called; it never says what shape v2 must serve.
Nothing can fail a build because v2 is different from v1 — only because v2
has drifted from its own record of what is left.

**Renames are the one thing you must record by hand.** `export_openapi.py` pins
dissolved v1 app names at zero, so every called `workflow_*` operation gets a
new name when it ports — 17 still to come. Add each to `renamed:` as you go: an
unrecorded rename makes the v1 name read as still-missing *and* the v2 name look
like a brand-new endpoint, corrupting the count in both directions at once.

### Reading the readiness marks

Each group below carries **Models / Services / Router**, because the difference
between them is the difference between an afternoon and a week. `apps/process`
and `apps/search` have `models/` plus `migrations/0001_initial.py` and little
else; **no group below is "backend done, needs only frontend"** unless its row
says so.

### The remaining groups

**Staff.** `accounts_staff_all_list`, `_create`, `_partial_update`,
`_icon_create` (the list op is done — superuser-only via
`staff_directory.list_all_staff`).
Models present: `Staff` incl. the `icon` ImageField ·
Services partial: `staff_directory.py` · Router partial.
Remaining ops unblock `staff/create-staff`. `_icon_create` is a
multipart upload — the only one in this group.

**Job — timesheets.** The daily + entry screens are built and their five
specs are green. Deferred with seams (no spec asserts them):
StaffDetailModal, MetricsModal, the entry page's Current Jobs cards, the help
dialog, container-level grid keyboard shortcuts.
`timesheet/workshop-my-time-view` remains its own slice — the calendar
rebuild (`@kodeglot/vue-calendar` has no React equivalent).

**Job — quote.** `job_jobs_quote_status_retrieve`, `_apply_create`,
`_link_create`, `_preview_create`.
Models present: `QuoteSpreadsheet` · Services partial: accept and revise
exist; apply/link/preview are Google Sheets sync and are deliberately
deferred (`apps/job/api.py:12`) · Router partial. The Sheets dependency is
the real cost here, not the endpoints.

**Job — quote-chat (SHOULD before cutover; AI).**
`job_jobs_quote_chat_retrieve`, `_create`, `_partial_update`,
`_interaction_create`, `quote_chat_delete_all`.
Models present: `JobQuoteChat` · Services none (`apps/ai/services/` holds
only `llm_client.py`) · Router not registered. Must route through `apps/ai`
(ADR 0041). No spec covers the chat tab, so it is stubbable for E2E.

**Job — reports.** `job_jobs_weekly_metrics_list`, `job_jobs_workshop_list`,
`job_job_completed_list`, `job_job_completed_archive_create`,
`check_archived_jobs_compliance`, `job_profitability_report`.
Models present · Services **none** · Router not registered. Each is a fresh
aggregation service, not a route over existing logic. No spec gates any of
them, and go-live does not need them.

**Xero.** `xero_sync_create`, `_sync_info_retrieve`, `_ping_retrieve`,
`_disconnect_create`, `_create_invoice_create`, `_delete_invoice_destroy`,
`_create_quote_create`, `_delete_quote_destroy`,
`_create_purchase_order_create`, `_branding_themes_list` — the counted
remainder is the operations still in the derived count; the foundation,
sync engine, invoice/quote/PO push and the operator commands are shipped
and E2E-verified where specs exist.

**Xero errors.** `xero_errors_list`, `_retrieve`, `_grouped_retrieve`,
`_grouped_mark_resolved_create`, `_grouped_mark_unresolved_create`.
Models present: `XeroError` · Services none · Router not registered. Admin
error views; no spec.

**Process documents — DEFERRED until after cutover, except safety AI.**
Forms, procedures, JSA, and the categories endpoint are deferred. The four
safety-AI operations are SHOULD before cutover under the AI rule; they do
not pull the rest of the surface into pre-cutover scope.
Models partial: `Form`, `FormEntry`, `Procedure` (JSA/SWP are
`document_type` variants — `Procedure.job` is "required for JSA, null for
SWP/SOP" — so the 2 JSA ops are not a third model). **There is no category
model**, so `process_categories_retrieve` is greenfield · Services none ·
Router not registered. The 4 safety-ai ops must go through the gateway
(ADR 0041). Only `process_forms_entries_list` is on a spec path, and
`form-entries-page-scroll` seeds itself over the API — a thin slice greens a
spec while the rest do not.

**App errors.** `app_errors_retrieve`, `_grouped_retrieve`,
`_grouped_mark_resolved_create`, `_grouped_mark_unresolved_create`,
`rest_app_errors_retrieve`.
Models present: `AppError`, **written from across the codebase** · Services
none — the write path is done and the read path does not exist · Router not
registered. Serves the AppError viewer (admin tail, SHOULD-plus).

**AI providers (SHOULD before cutover; AI).** `workflow_ai_providers_list`,
`_retrieve`, `_create`, `_partial_update`, `_destroy`,
`_set_default_create`.
Models present: `AIProvider` · Services partial: `llm_client.py` only ·
Router not registered. Must route through `apps/ai` (ADR 0041). The local
Gemini key lives in an `AIProvider` **row**, not env.

**Session replays.** `session_replay_recordings_list`, `_create`,
`_recording_chunks_create`, `_recording_events_retrieve`,
`_frontend_errors_create`.
Models present · Services none · Router not registered. No spec covers it,
and `rrweb` is not in v2's frontend.

**Operations.** `operations_workshop_schedule_retrieve`,
`_recalculate_create`.
Models present · Services none — **there is no scheduling algorithm at
all** · Router registered. Serves `pages/schedule.vue` (992 lines). No spec;
this is the group whose op count (2) most understates its cost.

**Search events.** `search_events_click_create`.
Models present: `SearchTelemetryEvent` · Services none · Router not
registered. Nothing writes it — the layer-contract deferral is recorded at
`apps/company/services/company_rest_service.py:597`.

**NotebookLM CRUD (SHOULD before cutover; AI).**
`workflow_notebook_lm_links_list`, `_retrieve`, `_create`,
`_partial_update`, `_destroy`.
Models present · Services none · Router not registered (only `_menu_list`
is served). The admin screen behind the navbar menu.

### Do NOT port: the operations nothing calls

Beyond the work list above, v1 exposes operations with **zero call sites in its
own frontend** — the second figure in the table's "still to port" row. They are
dead surface, and porting them is work no spec can ever verify. Confirm a call
site exists before porting anything not grouped above.

The same rule has one frontend entry: **v1's `pages/purchasing/pricing.vue` is
not the pricing-upload feature — do not port the file** (decided 2026-08-14).
The page as deployed (verified on v1's `origin/production`) accepts a dropped
file and discards it: the handler is a `debug`-library log line, it makes zero
API calls, and `git log --all -S` shows no frontend caller of the extraction
endpoint in any branch of v1's history. **The capability itself — upload a
supplier price list, extract it, link scraper products to DB products — is
committed deferred work**, delivered by the price-list-extraction slice and
the mappings slice, both pre-scoped above.

## Remaining non-API work

| Item | Notes |
|---|---|
| **Frontend SPA** | The largest remaining item by a wide margin — own section below |
| quote-to-PO | **SHOULD before cutover (AI)** — v1 `purchasing/quote_to_po_service.py`, incl. its inline Gemini client → the gateway |
| Middlewares | AccessLogging, DisallowedHost, **FrontendRedirect** (serves the SPA — needed, not optional), PasswordStrength |
| Ops | Dropbox API sync |

## The frontend rebuild

Real pages so far: login, `/jobs/create`, job detail, daily/entry/weekly
timesheets, the kanban board (desktop + mobile, live-updating), purchasing PO
list/create/detail and stock, CRM company list/detail, and the job-movement and
WIP reports. shadcn/ui is installed
(`components.json`, new-york/slate, the radix-era 2.x CLI — the v4 CLI's
presets diverge from what v1's specs assert on); add primitives with
`npx shadcn@2 add <name>`. Standing contracts (DataTable/QueryState
ownership, the auth path, kanban reconciliation invariants, PO grid
constraints) are in
[`frontend/docs/architecture-contracts.md`](../frontend/docs/architecture-contracts.md).

### Remaining build items by leverage

LOC are v1's, as a size signal — several should shrink.

| Component (v1) | LOC | Specs | Note |
|---|---|---|---|
| `/timesheets/weekly` page | 986 | 1 (authored) | Built, spec green. Needs one manual demo-tenant post before it counts |
| `WorkshopTimesheetCalendar` rebuild | — | 1 | `workshop-my-time-view`; no React equivalent of `@kodeglot/vue-calendar` |
| Labour Rates card + price-cap/RDTI/urgent controls | — | 0 | On `JobSettingsTab`; no spec asserts them (admin tail) |

**Cheapest greens, independent of the job flow — fill-in work, not next
work.** Still cheap and unstarted:
`process-documents/form-entries-page-scroll` (seeds itself over the API —
needs the process-forms backend slice first, so its true cost is the process
group's). The remaining two report specs (`sales-forecast`,
`payroll-reconciliation`) only read restore-populated mirror tables — they
are ordinary frontend slices and among the cheapest greens available.

Formatting in the backend is a bug — the wire carries numbers and the
frontend formats (ADR 0046). A schema declaring `str` for a quantity is the
review smell.

### v1 → v2 library mapping

Recorded so nobody re-derives it or hand-rolls primitives:

- **v1 is shadcn-vue** (style new-york, baseColor slate, lucide) — 3,045 LOC
  under `components/ui/` across 28 primitives. shadcn-vue is a port *of*
  shadcn/ui React, so `npx shadcn add` reproduces the same class strings
  **and the same `data-slot` attributes the specs assert on** (and
  `[data-sonner-toast]`). Same upstream relationship for `vaul-vue` → `vaul`
  and `vue-sonner` → `sonner`. **Install the primitives; do not write
  them.**
- **Missing deps the untested clusters need:** a date library (v1 uses
  date-fns + date-fns-tz + dayjs + `@internationalized/date`), `quill`
  (specs assert `.ql-editor`).
- **Needed by no spec, so do not port:** `pdf-vue3` (both print specs stub
  `window.open` and assert `%PDF` bytes), `@unovis` (zero consumers in v1's
  `src/`), `vue-advanced-chat`, `rrweb`.

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
`useQuery(fooOptions({ path: { id } }))`), and zod schemas. ADR 0021 plus
`scripts/check-api-boundary.mjs` make it the only permitted API access.

## Porting the E2E suite

v1 has **40 spec files**; the ported count is derived in the table at the top.
Case counts are deliberately not tracked here — a spec is green or it is not.

### What carries over unchanged

- **v1's `data-automation-id` values.** 342 distinct ids, and roughly a fifth
  of v1's selectors bind to them — that fraction ports as-is, as do its
  `getByRole` and `getByText` selectors. The rest are structural or css.
- **`tests/scripts/`** — DB backup/restore, sequence sync and safety checks
  are database-level, as is the auth fixture's API login.

### The spec table

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
| `timesheet/weekly-payroll` | `/timesheets/weekly` | standalone | **yes** | ids |
| `timesheet/workshop-my-time-view` | `/timesheets/my-time` | own job |  | ids |
| `example` | — | — |  | placeholder, delete on port |

**6 specs touch a live Xero tenant** (`company-defaults` test 3,
`crm/people`×2 setup, `create-job-with-new-company`, `job-xero-invoice`,
`job-xero-quote`, `timesheet/weekly-payroll`). The last of those is the only
one that WRITES to payroll: it posts a week of hours and reads back what Xero
holds, which is why the payroll path cannot be proven by the unit suite.
Four rows previously carried a wrong "Live Xero: yes":
`sales-forecast`, `payroll-reconciliation`, `create-timesheet-entry` and
`job-cost-entry-data` only read restore-populated mirror tables. One seed
constant gates the shared-fixture specs:
`TEST_COMPANY_NAME = 'ABC Carpet Cleaning TEST IGNORE'` (`helpers.ts:7`).

### Harness: still missing

**Sync-window open/close** (seam comment atop `global-setup.ts`) — only
consumed by the sync loop; kanban waits only on its own board. v1's rich
login diagnostics are debugging aids, not blockers; port them if a flaky
login ever needs them.

The config keeps `fullyParallel: false`, `workers: 1`, `maxFailures: 1`,
`timeout: 120000`, `actionTimeout: 0`, `trace: 'on'`. The suite is serial by
design, so **raise `maxFailures` on the CLI when triaging**
(`--max-failures=10`).

## Deferrals carried inside completed slices

Each has a loud seam in code (`grep -rn "Phase 4\|Phase 5\|SEAM" apps/`); listed
so they are not rediscovered by accident.

- **Xero (Phase 4):** Xero-synced company update;
  `Company.get_company_for_xero`. Two things left this list and neither is a
  seam any more: payroll pay-run create/refresh, the calendar anchor and the
  week posting (`apps/xero/payroll_push.py`, `payroll_leave.py`, ADR 0007), and
  employee sync — `sync_staff` and the seed's employees phase are ported and
  have run against the live demo organisation. The one payroll-employee
  direction still unported is `import_staff_from_xero`, which creates Staff
  FROM payroll employees for a fresh prospect instance; it needs the employee
  salary and working-pattern reads and is on no restore path.
- **Search telemetry:** company search, kanban search and stock search all emit
  the structured log line but write no `SearchTelemetryEvent` (layer contract) —
  returns with the search slice.
- **Quoting:** PDF price-list extraction (`extract_price_data` raises a named
  error). The browser layer is ported and tested against a fake WebDriver;
  what CANNOT be tested locally is whether the selectors still match the live
  portal — see the stale-selector list in `scrapers/steel_and_tube.py`, and
  validate with `manage.py run_scrapers --supplier "Steel & Tube" --limit 2`
  against production credentials. **Not on the cutover critical path**: without
  price extraction the scraper carries no business value, so both halves are one
  post-cutover feature and neither blocks the flip.
- **Job:** `update_completion_checklist`; weekly-metrics; invoices/quote GET
  endpoints; quote apply/link/preview (Google Sheets sync).
- **Purchasing:** re-receipting a line deletes prior stock but keeps
  accumulating `received_quantity` — ported v1 debt, ledgered, needs a
  deliberate stock-reconciliation decision. PO detail deferred seams:
  receipt/allocation column + AllocationCellEditor, PoCommentsSection/events,
  PendingItemsTable, PDF/email dialogs, line delete, price_tbc,
  expected-delivery edit, supplier re-pick.
- **Timesheet:** grid/page seams — StaffDetailModal, MetricsModal, Current
  Jobs cards, help dialog, container-level keyboard shortcuts.
- **Costing grid seams:** duplicate-line, unit-rev override bookkeeping on
  server rows, data-freshness polling, the actual tab's approve
  button/pending badge, the Source column, negative-stock badges, the Actual
  Summary aside/dialog, Estimate/Quote comparison chips.
- **Shell:** the data-versions freshness *subscription* beyond the initial
  fetch is live for kanban only; other surfaces consume the same stream and
  document when they arrive (ADR 0047) — never a second stream or event.

v1's operational assets are inventoried in
[`v1-disposition.md`](v1-disposition.md): **ported** (with v2 path),
**dropped** (with the rejecting fact), or **`blocked-by:<feature>`** — and a
slice landing one of those features converts its blocked-by rows in the same
PR. The scrubbed-dump producer's live rehearsal before the v1 production
hosts are decommissioned is a cutover-checklist item.

## Post-cutover — decided, deliberately NOT before 22 August

Each of these has an answer already; none blocks an E2E spec, so none earns a
day before the date.

1. **A client error IS an AppError — invert the rule.** Decided 2026-08-07.
   422s already persist; the change is that service-level client errors must
   too. `PhoneCallRecord` is append-only — nothing in `apps/` deletes one — so
   "Phone call not found" for a well-formed id can only be a client bug, id
   probing, or an id from another environment. Work: the 12 assertions across
   6 files requiring `AppError.objects.count() == before` invert,
   `TestClientErrorsDoNotPersistAppErrors` gets renamed, ADR 0019 records the
   reasoning. Do 2 with or before this.
2. **AppError retention: 90 days resolved, 365 unresolved.** Decided
   2026-08-07. Nothing deletes an AppError today. `persist_app_error` dedupes
   per exception *instance*, so each request costs a row; the size driver is
   the `data` JSONField holding a full traceback.
3. **WIP report: bound invoices by the report date, and stop dropping unbilled
   jobs from the cost view.** Decided 2026-08-07. Deliberately post-cutover:
   both halves change reported numbers on the day they ship. Needs a
   behaviour-ledger entry and someone telling whoever reads the report.
4. **Response nullability, which shrinks per slice rather than in a sweep.**
   The count is in `docs/code-quality.md` under *Wire contract*. Presence is
   settled (optional response properties pinned at zero). **When a slice
   ports a screen, the response schemas that screen reads declare `| None`
   only where the producing service can actually return `None`.**
5. **Single-source the numbers in this file.** Prose still restates figures
   the derived table owns, which is exactly what went stale twice.
6. **Purge "v1" and "v2" from everything: comments, docstrings, docs, ADRs,
   filenames.** The words are banned once the port is over. **We document
   state, not change.** A comment saying "v1 silently substituted the company
   default; v2 raises" becomes "a staff member without a wage rate cannot be
   costed". Scope is wide, so budget for it: this file (deleted at cutover),
   the cutover checklist, ADRs carrying "ported from" reasoning, the
   behaviour ledger, the `db_table = "workflow_*"` overrides,
   `scripts/v1-frontend-operations.yml` and its generator,
   `export_openapi.py`'s `DISSOLVED_V1_APPS`, and the port-progress rows in
   `status_table.py`. **Delete first, reword only what states a live
   invariant.**
7. **Ratify every AI-argued ADR exception with the owner — KAN-342.** ADR 0051
   makes a model-originated rationale an unratified claim, so the codebase
   carries exceptions to its own ADRs and gates that no human signed off: 613
   `noqa`, 374 attributed rationale blocks, 96 `deliberate-swallow` sites, 25
   other suppressions and 103 behaviour-ledger deviations, overlapping. Each
   item ends ratified (model prefix replaced by a durable authority citation),
   rejected (a defect wearing a justification — fix the code), or superseded
   (the ADR moved).
   **Do the rule-level rulings first — they are what makes this days, not
   months.** DJ001 (153), PLC0415 (124) and E402 (100) are 59% of all
   suppressions and look like one policy each: DJ001 plausibly falls out of
   ADR 0040, PLC0415 is the deliberate call-time-import pattern that breaks
   cycles under the layer contract, E402 is Django-setup ordering.
   **315 of the 613 `noqa` carry no written reason at all**, so for those there
   is nothing to adjudicate until someone reconstructs intent — worse than an
   AI-written reason, which at least states a claim that can be tested. 245 of
   those 315 sit inside the big three and clear with the rulings; the ~70
   outside need reading one at a time, chiefly BLE001 (14) and C901 (14).
   S603, the security-sensitive rule, has zero unreasoned sites — the sloppiness
   is in the structural rules, not the dangerous ones.
   The attributed count covers only the branch that was swept; rationale
   elsewhere is unmarked legacy of unknown provenance, which ADR 0051 says is
   **not** evidence of approval and whose model family must not be guessed — so
   establishing the true denominator is a task, not an assumption.

## Engineering backlog (no decision needed, just work)

1. Port v1's kanban search-ranking test net (~30 tests). The scoring code is
   line-identical to v1 but the regression net is thin (4 tests).
2. CRM wire-pin tests (portal login/CDR form fields, `b"200"` strip,
   `Result == "1"`, timeouts) and superuser-gate tests on recording deletes and
   endpoint CRUD.
3. Hoist connection hygiene (`close_old_connections` guarded by
   `in_atomic_block`) into `apps/core`: four copies exist and
   `apps/crm/tasks.py` still has two unguarded calls.
4. Unify invalid-state handling across document managers: the invoice manager
   still raises `ValueError` for "job already paid" (a 500 via the envelope)
   where the quote sibling refuses with readable 400 values. Include the
   provider: `create_invoice`/`delete_invoice` should adopt the quote/PO
   `summarize_errors=False` + element `validation_errors` pattern.
5. Ultrareview sub-cap cleanups from the quote slice: managers read
   provider-private `_sub_total`/`_total` raw keys; `EMPTY_SERVER_SHAPE`
   could be a `Pick<CostLineOut, ...>`; XeroQuoteCard/JobInvoiceCard sibling
   drift; undebounced stock search in the item picker; duplicated HOURS
   formatter; a dead "No online URL" toast.
6. **The kanban board has no non-drag way to change a job's status on
   desktop** — the card's status button is `lg:hidden`: a WCAG 2.1 SC 2.5.7
   defect. Fix with pragmatic-drag-and-drop's documented action-menu
   alternative, not a hand-rolled shortcut layer. Until then the job-detail
   header is the non-pointer status path.
7. Root `conftest.py` guard failing any test that attempts a real network
   call. `LLM_BOUNDARY` is module-bound, so a second consumer of
   `chat_completion` silently patches nothing.
8. **SHOULD before cutover (AI): no timeout, retry or spend cap at the LLM
   boundary.** litellm's default `request_timeout` is 6000s, so a hung
   vendor pins a worker for 100 minutes. ADR 0041 claims the gateway is
   where these live; make that true.
9. Rewrite the known-weak tests instead of leaving green-but-meaningless
    assertions: `test_price_extraction.py:48,:59` (asserts docstring
    headings; the no-vendor-SDK grep misses `from mistralai import` — AST it
    or use an import-linter contract), `test_llm_client.py:195`
    (constant == constant), `test_scheduled_tasks_api.py:96`,
    `test_stock_metadata_tasks.py:102-155` (mocks the unit under test),
    `test_products_are_saved_in_batches_during_a_long_run` (vacuous), and
    `test_a_mapping_with_no_item_code_is_simply_not_in_xero` (tautological).
10. Untested paths worth a net: the per-row savepoint in `save_products`,
    `_save_mapping`'s concurrent-parse branch,
    `scheduled_task_service.py`'s malformed-entry guards, and
    `MAX_FAILURE_RATIO`'s 50% boundary (`>` vs `>=` untested).
11. `to_optional_decimal` has a pre-existing sibling `_decimal_or_none`
    (`crm/services/phone_call_service.py:1017`) with NO `is_finite()` check,
    writing `Decimal("NaN")` into the call `charge` money column.
12. **Six unrecorded API deviations** to ledger or fix, incl.
    `render_schedule` strings and search not implementing DRF's token
    splitting (`?search=entry apps.job` → v1 120 rows, v2 **0**).
13. **Docstrings that assert behaviour the code does not implement.** The
    beat-wiring advice and the litellm stub's justification.
    `is_discontinued`'s `help_text` lies, and editing it is a migration
    while v2.0 migrates by pg_dump/restore — make the flag mean something or
    drop it before cutover.
14. **Service TypedDicts declaring `str` ids whose wire mirror says `UUID`.**
    `apps/company/services/duplicate_identity_report.py` carries five
    (`DuplicateCompanyMember.company_id`, `DuplicatePersonSummary.person_id`,
    `DuplicatePersonCompanyLink.link_id`/`.company_id`,
    `DuplicatePersonContactMethod.method_id`); each mirror in `schemas.py`
    declares `UUID`. The parity diff cannot see this class when the wire
    schema is already correct — finding the rest means reading each app's
    `services/*.py` TypedDicts against its `schemas.py`.
15. **Three defects the handler-gate annotation surfaced (PR #26 review)**,
    deferred so a behaviour change would not ride a test-gate PR:
    `time_entry_rates.py:76` (`to_decimal` maps an unparseable stored
    multiplier to the default — absent keeps the default, present-but-
    unparseable should raise; measured 0 malformed of 13,931 rows);
    `phone_call_service._positive_int` (`float("inf")` passes the isinstance
    gate and `int()` raises OverflowError — reject non-finite floats up
    front); `job.py:688 has_quote` (catch `ObjectDoesNotExist`, not bare
    `AttributeError` — the pattern at `kanban_service.py:520`).
16. **`X | None` returns.** The live count is the *Optional returns* row of
    the generated `docs/code-quality.md`. ADR 0045 makes this a rule going
    forward; the existing sites are a post-cutover sweep, not a blocker.
17. **PR #26's final commit `72a7118` was never reviewed** (CodeRabbit rate
    limit) — it closes four holes in the handler gate, and three earlier
    rounds each found real holes in that same file. Re-review
    `config/tests/test_exception_handler_contract.py` when the deferred
    fixes above touch it.
18. Cosmetic: `base.py:352` fetches all known URLs then discards them when
    `refresh_old`; `scheduled_task_service.py:119` unreachable-false guard;
    `llm_client.py:80` truthiness-tests a `str | None`; `llm_client.py:116`
    sets a module global on every call.
19. Timesheet-entry review leftovers (both inherited shapes, neither
    spec-asserted): a draft's stale `labour_subtype` surviving a job repick
    can make `rateForSubtype` throw (v1 misbehaves too — unified behaviour
    needs a decision); `SmartTimesheetTable`'s focus handoff queries
    `document` rather than the grid's root.
21. Run `find_duplicates.py` over `frontend/src/` (see Where things stand).
