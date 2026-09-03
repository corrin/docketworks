# Work remaining

**This file only shrinks.** Every line is a requirement for the near future, and work
is deleted the moment it is finished. Anything worth saying that is not a task — a
ruling, a finding, a measurement — goes to [`rewrite-history.md`](rewrite-history.md),
so explaining something never grows the file a session reads to find its next job.
Constraints that would otherwise be re-broken are the one exception, and they sit at
the bottom.

A task gets as many lines as a session needs to pick it up cold — no more. It never
restates the code, re-derives a measurement, or narrates how it was found; where a fact
must survive it belongs in an ADR or a seam comment, and the task links there.

**Every KAN ticket raised from 2026-09-02 gets a line here, in the same sitting.** One
or two lines, enough for a session to pick it up cold, linking to the ticket rather than
restating it — the ticket stays the authority for the reproduction, the evidence and the
acceptance criteria. The point is that finding the next job means reading one file.
Raising a ticket and not logging it is how that stops being true.

**The rule is forward-only, and this file is not yet the whole list.** 143 tickets
predate it and live in Jira alone; they were not backfilled because most are long-tail
wishes and this file's first line is that every entry is a requirement for the near
future. Until that backlog is triaged, check Jira as well before concluding something
is not already raised. Work with no ticket lives here in full: the tail of the port,
cross-cutting debt, seams left inside completed slices, and decisions waiting on the
owner.

**Numbers.** Only two kinds belong in a file that is rewritten as often as this one:
derived and gated by `status_table.py --check` (the table below owns them), or a frozen
fact about v1, which cannot rot. Estimates of unfinished work belong nowhere — say which
thing is bigger, never by how much.

## Where things stand

The port-progress rows count operations v1's frontend called that v2 does not serve.
They are a work list, not a countdown to a release — each one is capability the business
does not have.

| Measure | Value |
|---|---|
| E2E specs ported | **51 spec files** (v1 shipped 40; the screens whose specs are still unwritten are listed below) — green is the only measure that counts |
| Backend operations still to port | **53** (see below; 31 more exist but nothing calls them) |
| API operations v2 exposes | 247 (`frontend/schema.v2.yml`, kept fresh by its own gate) |
| Unit tests | 2891 (all passing) |
| Coverage | above the 88.4 fail_under floor (coverage's own gate on CI's pytest --cov run; ratchets up per slice — never down) |
| Type/lint debt | zero mypy baseline, every suppression counted in [`code-quality.md`](code-quality.md), all gates on every commit |
| Behaviour ledger | 125 recorded deviations |
| ADRs | 41 (v1's 26 carried forward + 0038–0041, 0043, 0045–0054 written here) |

**Written is not delivered.** Report progress as specs green; a count of endpoints
written measures typing, not delivery. Every slice below authors its own E2E spec and
is done only when that spec is green.

**Record every rename by hand as you port an operation.** 17 `workflow_*` operations
are still to come, and `scripts/v1-frontend-operations.yml` is where a rename is
recorded. An unrecorded rename makes the v1 name read as missing *and* the v2 name look
brand new, corrupting the count in both directions. That file is a **work list, not a
contract authority** — it records which operations v1's frontend called, never what
shape v2 must serve.

## Start here

Not a tier — just the five things a session should have a reason not to pick up.

1. **[KAN-356](https://docketworks.atlassian.net/browse/KAN-356): payroll posting
   double-books leave, and reports `ok` while doing it.** Live in production, and money
   is already out the door — $1,442 gross overpaid and 40h double-debited for one
   employee, on each of two consecutive weeks; the second was caught only by a
   hand-entered offsetting line. `reconcile_leave_for_staff_week`
   (`apps/xero/payroll_leave.py:327`) skips any Xero leave application not fully
   *contained* in the posting week, so a multi-week application entered in Xero is
   invisible and `_create_leave` writes a second one on top. `posted_leave_hours`
   (`:293`) applies the same containment rule, which is why `posting_status_for_week`
   reports a match on the doubled week. Detect overlap, refuse, and name the Xero leave.
2. **Eight production `Procedure` rows link dead Google Docs — one is on a clock.**
   Doc.363 Milling Machine SOP is in Drive trash and its 30-day purge window opened
   2026-08-26. Untrash it before that expires. The other seven are invisible even to
   the Workspace owner; the owner arbitrates restore-from-backup vs archive per doc,
   then the surviving rows are relinked or archived on the production instance — a data
   fix, never a read-side fallback (ADR 0015). The row list is in `rewrite-history.md`.
   Re-verify with `outbound_links_probe --kind google_file --google-as delegated`.
3. **Port the workshop schedule.** No route, no `AppNavbar` entry and no algorithm, so
   the shop plans without it. See Screens for the port target and the two defects not to
   reproduce.
4. **[KAN-335](https://docketworks.atlassian.net/browse/KAN-335)** was written "blocked
   until production cutover is complete" and is now unblocked. It restores the
   `format: uuid` contract the port dropped on 424 properties, extends
   `schema_parity_diff.py` to see property types at all, and gives `CostLine.meta` one
   definition instead of three. Its step 1 generates the work list for its step 2, so
   nothing here is hand-listed.
5. **`/purchasing/mappings`** has been labelled "this slice lands first" since before
   the flip and is still unbuilt three releases later. Either it lands or it stops
   claiming to be first.

## Operations

- **Decommission the v1 production hosts**, and first its blocker: **rehearse the
  scrubbed-dump producer live**, which is the last thing still running on them.
  `scripts/ops/pull_prod_backup.sh:87` still says "v1 hosts stay live until cutover" —
  fix that comment when the rehearsal lands.
- **Confirm the sitemap shard count** on the next live Steel & Tube portal run. The
  2026-08-01 measurement found a single shard at 3,677 URLs against a 50,000 limit, and
  `MIN_SITEMAP_COVERAGE` (`apps/quoting/scrapers/base.py:65`) is the defence; nobody has
  re-read it against the live portal. Do it with the run the next item needs anyway.
- **Supplier-scraper ruling**: the Steel & Tube scrape has been silently dead since
  February 2026 — decide deliberate-stop vs site-change, then fix or record. The live
  run is `manage.py run_scrapers --supplier "Steel & Tube" --limit 2` against production
  credentials, and it is also the only way to test the portal selectors (see Seams).
- **Credential rotations**: the Google service-account key committed in v1's history,
  and `frontend/.env.test` in this repo's history.
- **Retire the prod root backup cron pair** (00:00 backup + 00:10 cleanup-as-root) only
  AFTER one green manual run of `backup-db-msm-prod.service` — the root cron's
  rclone-as-root upload is the load-bearing off-site path until the unit works.
- **Migrate the ~11.3 GiB of backup history** out of the personal Drive into the
  client's Admin shared drive (owner ruled: client backups live in the client's drive).
  Copy, verify, then remove the personal-Drive copies.
- **Make `backend` and `frontend` required status checks** in GitHub branch protection —
  PR #105 auto-merged while the backend suite was still running.
- **Alert on a paused Maestral, not a dead one.** A paused sync leaves the process alive,
  so `systemctl` reports active and `Restart=always` never fires; the alert must parse
  `maestral status` for paused and sync-error states, not process liveness.
  `verify-instance.sh` gates JobFile bytes on disk, which catches a long outage's
  *effect* at verify time only — the periodic host-side check is unbuilt.
- **MariaDB archaeology on the prod host**: localhost-only MariaDB holds `jobs_manager`
  (the pre-DocketWorks ancestor) and a legacy mysql-era `dw_msm_prod`. Identify any
  consumer, archive, remove the service.
- **Backup-system consolidation handoff**: fold the prod-side diagnosis (Part B of the
  prod host's `/root/.claude/plans/right-obviously-the-systemd-shimmying-origami.md`,
  file:line pointers included) into the work above; it documents the two-upload-path
  history and the config-only fix.

## Payroll and Xero

- **The pay-run mirror deletes rows it never fetched, under a docstring promising it
  cannot.** `sync_pay_runs` (`apps/xero/payroll_push.py:759`) runs
  `XeroPayRun.objects.filter(xero_tenant_id=tenant_id).exclude(xero_id__in=live_ids).delete()`
  beneath a docstring asserting "Both callers use `get_pay_runs_for_sync`, which asks
  Xero for the lot" — which is false. Neither `get_pay_runs_for_sync` nor
  `get_pay_slips_for_run` (`apps/xero/payroll_sync.py:49,63`) passes `page` or reads
  `pagination`, and the SDK page size is 100, so past 100 pay runs the mirror silently
  deletes real rows and cascades their slips. Reuse
  `payroll_employees._raw_employees`, which terminates on Xero's own `page_count`; it
  needs `pagination` added to `PayRuns`/`PaySlips` in
  `stubs/xero_python/payrollnz/__init__.pyi` (the class exists at `:117` and is already
  wired to `Employees`). Fix the docstring with the code.
  [KAN-354](https://docketworks.atlassian.net/browse/KAN-354) carries the analysis. It
  is marked Done with no commit behind it, so its status is not evidence the fix exists.
- **The overtime repair commands price 1.5x/2x lines at the base wage.**
  `create_overtime_entries.py:194` writes `"unit_cost": str(staff.base_wage_rate)`
  unmultiplied, and `_repair_shared.build_repair_time_line` takes `unit_cost` and
  `wage_rate_multiplier` as independent parameters that never meet — the multiplier
  reaches `meta` and never the price. The tests now **pin** the defect
  (`apps/timesheet/tests/test_repair_commands.py:234` asserts a 1.5 multiplier beside a
  base-rate `unit_cost`; `:367` the same on the split path), so fixing it means changing
  them too. Route pricing through `apps/job/services/time_entry_rates.py`. The
  historical-row question — whether already-written rows get repriced — needs an owner
  ruling, and no migration exists. These commands write real payroll cost lines: dry-run
  and read the CSV before running either.
  [KAN-339](https://docketworks.atlassian.net/browse/KAN-339) carries this and is
  likewise marked Done with no commit behind it.
- **Make the week reconciliation poll pay slips to a deadline.** ADR 0007 records the
  gap: `get_week_reconciliation` makes a single unguarded `get_pay_slips_for_week` call
  while a Draft run's slips recompute asynchronously for minutes after a post, and the
  page is reached by a link clicked in exactly that window. Poll to a deadline and fail
  on expiry; never converge on agreement with our own figures. `PaySlip.lastEdited`
  (absent from the hand-written stub) may be the convergence signal.
- **Settle whether `PAYROLL_SLEEP_SECONDS` should exist.** The OPEN QUESTION at
  `apps/xero/constants.py`: `RateLimitedRESTClient` already paces and absorbs
  minute-limit 429s, so the manual payroll pacing layer may be a second implementation
  of handled behaviour. Deleting it changes live pacing and needs one clean fresh-quota
  integration run to settle.
- **Scope the hourly pay-slip sync** to Draft and not-yet-mirrored runs. It is N+1 by
  its own docstring and runs hourly over all entities: 21 Xero calls per sync becomes 2,
  and it grows 24/day for every new weekly pay run. Xero has no all-slips endpoint, so
  scoping is the fix, not batching — a Posted run's slips are final (ADR 0007). Drop the
  duplicate `get_pay_runs` inside `get_all_pay_slips_for_sync` with it, and assert the
  call count (ADR 0052).
- **Per-(endpoint, day) Xero telemetry** at `RateLimitedRESTClient.request`, the one seam
  every call crosses. It already has `method` and `url` but keeps only a snapshot
  overwritten per call and warnings at 10 remaining — too late to act on. A daily
  per-endpoint counter makes "where did the quota go" a query.
- **Reconcile payroll without waiting for a sync.** The report compares against
  `XeroPaySlip`, which exists only once a run is Posted and mirrored, so it cannot answer
  when the mistake is still cheap to fix. Generalise the weekly panel's live read
  (`week_posting_status`) from one week to a date range. Gross pay stays slip-sourced — a
  timesheet line carries units, not dollars — and the live read costs one Xero call per
  staff per week, so it stays behind an explicit trigger.
  **Its core value is the employee nobody posted for** — Xero pays an employee on the
  calendar their pay-template hours when the run holds no timesheet for them, so the
  reconciliation must be driven from Xero's employee list, not the app's.
  `payroll_employees.get_employees()` already pages it and `existing_timesheets_for_week`
  returns the posted ids; the at-risk set is the difference. Two per-employee facts are
  still missing: calendar assignment and termination.
- **The payroll SDK boundary has inline siblings.** `payroll_sdk.payroll_api` is the
  declared one home for building the payroll client, but `payroll_sync`, `payroll_setup`,
  `payroll_employees`, `scripts/ops/xero_payroll_probe.py` and
  `scripts/ops/outbound_links_probe.py` still construct `PayrollNzApi(get_api_client())`
  inline (17 sites) and mostly resolve `get_tenant_id()` themselves — outside the posting
  path the tenant threading covered, but siblings of the module that owns the concept.
  `transforms.transform_pay_slip` (two sites) also still stamps mirror rows from a fresh
  singleton read; `transform_pay_run` now takes the caller's tenant.
- **Run the two remaining payroll-write E2E specs on a fresh day's Xero quota:**
  `E2E_XERO_PAYROLL=1 ./scripts/ops/run_e2e.sh --grep "@xero-payroll-write"`. The primary
  spec — hours reach Xero and Xero holds what was recorded — passed 2026-08-21 after the
  owner deleted the stale draft; the re-posting and replacement specs then hit the day
  limit (quota resets ~19:00 NZT) and have never been green.
- **Opt-in integration test for provider-side recording deletion.** `deleteMedia` is
  irreversible on the one live 2talk account with no undo, so it stays out of the merge
  gate (ADR 0050's opt-in exception). The compensating test runs only under
  `PHONE_PROVIDER_DELETE=1`: it deletes one recording already archived locally and older
  than 31 days — what the nightly task does in production — and reads back that the
  provider no longer serves it.
- **Xero remainder:** the five `xero_errors_*` admin views. Everything else this row once
  listed is done and consumed: ping, sync, sync-info and disconnect by the `/admin/xero`
  connection page (spec `admin/xero.spec.ts`), invoice/quote/PO create-delete by the job
  and purchasing screens, branding-themes by the company-defaults screen.

### Owner: check one production pay slip for a double-paid public holiday

Open a posted production pay run covering a public holiday — the week of 22 Dec 2025 or
2 Feb 2026 — and look at one full-time employee's pay slip. If it carries BOTH a
`Public Holiday (…)` earnings line and 8 hours of Ordinary Time for the same day, roughly
704 hours across nine dates since 2025-06-02 were paid twice, and that is a correction to
make in Xero; no code change recovers it. If only the Ordinary Time line is there,
production's holiday settings differ from the demo organisation's and removing our
posting would UNDERPAY, so the mechanism has to be re-examined before anything changes.

It cannot be answered from a restored database: pay slips mirror only for Posted runs,
the tenant now points at the demo organisation, and the demo slips that prove the
mechanism belong to employees with no overlap with our staff. Mechanism and posting
surfaces are in ADR 0007.

This is a sibling of [KAN-356](https://docketworks.atlassian.net/browse/KAN-356), not a
duplicate — that one duplicates Employee Leave applications, this one adds Ordinary Time
on top of a holiday line Xero computes itself and offers no API to suppress. Both are the
same class: the post duplicates what Xero already holds, and then self-reports success.

## Screens

- **Schedule.** Port v1's scheduler — `apps/operations/services/scheduler_service.py`
  and `frontend/src/pages/schedule.vue` in the archived v1 repository — plus a page and
  a fresh spec. v2 holds only the schema shell: `apps/operations/models/job_projection.py`
  defines `SchedulerRun`, `JobProjection` and `UnscheduledReason`, and nothing reads or
  writes them. Scope `operations_workshop_schedule_retrieve` / `_recalculate_create` at
  pick-up. Do not reproduce two known defects:
  [KAN-331](https://docketworks.atlassian.net/browse/KAN-331) — a job that has fully
  consumed its estimate reports "No hours estimate"; its proposed fifth
  `UnscheduledReason` is a v2 migration too — and
  [KAN-332](https://docketworks.atlassian.net/browse/KAN-332), where the greedy
  worker-picker truncates to the assigned staff and starves a small job while the shop
  is idle.
- **Reports** — nine of eleven remaining are frontend-only against a done backend; only
  `job_profitability_report` and `check_archived_jobs_compliance` need backend work. No
  charting library anywhere in v1: every screen is cards plus hand-rolled tables, so
  porting is layout plus typed fetch. `kpi` is the largest (the `components/kpi/`
  calendar-and-modals tree, not the page; its backend landed with
  `accounting_reports_calendar_retrieve`); `sales-pipeline` looks large only because
  ~700 lines are an inline `h()` table that becomes plain JSX. Each authors a fresh spec.
  A new page also earns its `AppNavbar` Reports entry under the matching v1 section
  heading — Management, Reconciliation, or a Data Quality group that does not exist yet
  because no data-quality page does. Two v1 bug reports land with their pages rather than
  separately, because v2's backend already answers both correctly:
  [KAN-343](https://docketworks.atlassian.net/browse/KAN-343) (RDTI Spend, Management) and
  [KAN-344](https://docketworks.atlassian.net/browse/KAN-344) (Duplicate Identities, Data
  Quality).
- **`/purchasing/mappings`** — backend done and codegen'd (`listProductMappings`,
  `validateProductMapping`). One route plus one page in the `StockPage.tsx`/`PoListPage.tsx`
  shape, editing in a modal. Its spec covers the screen over scraper-sourced data.
- **Price-list extraction** — upload a supplier PDF, have AI analyse it, surface the
  results on the mappings screen: the manual-supplier twin of the scraper path. The seam
  note atop `apps/quoting/services/price_extraction.py` is the scope record. Routes
  through the gateway (ADR 0041), arbitrates the duplicate-detection conflict that note
  flags, and rebuilds `/purchasing/pricing` with a working upload. Its spec owns the
  cross-screen flow; the mappings spec asserts nothing about uploads.
  [KAN-176](https://docketworks.atlassian.net/browse/KAN-176) carries the business ask.
- **Attachment thumbnails and click-to-view** (prod bug report 2026-08-31). v1's
  attachments tab rendered a thumbnail per file and clicking it viewed the image; v2's
  `JobAttachmentsTab.tsx` renders only download/delete icons and nothing in
  `frontend/src/` calls the ported `getJobFileThumbnail` endpoint. Port the
  thumbnail-and-view UI and extend `job-attachments.spec.ts` to assert a thumbnail renders
  and opens. [KAN-334](https://docketworks.atlassian.net/browse/KAN-334) wants the same
  surface to preview more formats — do them together.
- **Process documents** — procedures and JSA. The forms half shipped; JSA and SWP are
  `document_type` variants of `Procedure`, not a third model.
- **The admin tail** — labour rates, archive jobs, the month-end UI (backend done) and
  the AppError viewer (write path done everywhere; the read/grouping API and page are
  unbuilt, and [KAN-192](https://docketworks.atlassian.net/browse/KAN-192) wants row
  resolution on it). None has a spec; each slice authors its own.
- **Labour Rates card and the price-cap/RDTI/urgent controls** on `JobSettingsTab` — no
  spec asserts them.
- **Email delivery** — general outbound email and system notifications are deferred, not
  retired (password-reset delivery shipped 2026-08-31). The slice will most likely extend
  the delegated Gmail sender in `apps/core/gmail.py`, its only consumer today, rather than
  add SMTP configuration (owner ruling 2026-08-31), and authors its own spec; the current
  PO `mailto:` composer is a separate capability and remains unchanged.
  [KAN-345](https://docketworks.atlassian.net/browse/KAN-345) wants the password-reset
  loop proven end to end with a real delegated send.
- **AI product work** — quote chat, safety AI, quote-to-PO, AI-provider administration and
  NotebookLM CRUD are deferred, not retired. Provider credential loading and the shared
  gateway already exist because every slice routes through `apps/ai` (ADR 0041); the local
  Gemini key lives in an `AIProvider` row, not env. Each user-facing slice authors its own
  spec.
- **Job — quote:** `_apply_create`, `_link_create`, `_preview_create` are Google Sheets
  sync; the dependency is the real cost, not the endpoints. When that Drive client lands
  in `apps/`, `scripts/ops/outbound_links_probe.py` becomes `manage.py check_links`
  (ADR 0049: it is a script only because the app does not read `GCP_CREDENTIALS` yet). The
  service-account JSON lands as a column on `IntegrationSettings` with that client
  (ADR 0053), never back in `.env`.
- **Job — reports:** weekly metrics, workshop list, completed/archive, profitability,
  archived-jobs compliance. Each is a fresh aggregation service.
- **App errors read path:** `app_errors_*`. The write path is done everywhere.
- **Search telemetry:** company, kanban and stock search emit the structured log line but
  write no `SearchTelemetryEvent` — the layer-contract deferral is recorded at
  `apps/company/services/company_rest_service.py`.

## Correctness and hygiene

- **The session-replay events endpoint validates its own output.** `response=RecordingEventsOut`
  (`apps/diagnostics/api.py:210`) runs the whole payload through pydantic against a
  recursive `JsonValue` union; on a 4.28 MB replay that is 0.81s of `validate_python` plus
  0.28s of `dump_json`, against 0.05s of gzip. Return the joined chunks without
  re-validating bytes the server just parsed. Measurements in `rewrite-history.md`.
- **`payload_available` costs a query and a stat per listed recording.** `_recording_out`
  (`apps/diagnostics/api.py:76`) calls `has_payloads`, which reads the first chunk row and
  stats its file — 50 of each per page of the admin list. `prefetch_related` does not fix
  it: the differing `order_by` defeats the prefetch. Stat the recording's directory
  instead — `PrivateFileStore.write` creates `{root}/{recording_id}/`, so it exists iff a
  chunk was ever written. That also stops a missing chunk 0 reporting "not on this
  machine" when the payloads are merely partial; the cost is that an empty leftover
  directory would report available and then fail on load.
- **Session replays download whole.** The admin player fetches every event in one response
  once the superuser asks to watch (hundreds of KB gzipped). `rrweb-player` exposes
  `addEvent`, so progressive playback is feasible, but it does not reduce the bytes and
  page one must still carry the full snapshot — do it for time-to-first-frame, not size.
- **`DataTable` carries a private `joinClasses`** (`frontend/src/features/shared/DataTable.tsx:117`)
  duplicating `cn` (`frontend/src/lib/utils.ts`). Not swapped in place because `cn` runs
  `tailwind-merge`, which drops conflicting classes rather than concatenating — a
  behaviour change on the editable grids that needs its own verification.
- **Make the one-implementation rule cover the whole application.** Run the Python gate
  over `apps/`, add an equivalent TypeScript check over `frontend/src/`, hoist the Celery
  connection-hygiene copies into `apps/core` — seven task modules carry them
  (`apps/{xero,quoting,purchasing,job,crm,operations,diagnostics}/tasks.py`, plus
  `apps/xero/management/commands/start_xero_sync.py`), and `apps/crm/tasks.py`'s two calls
  are unguarded — and add a root test guard failing any unmarked real network call.
  `find_duplicates.py` is `types: [python]`, so nothing on the frontend is checked at all
  — three parallel job pickers coexisted through every green tier until a human caught
  them.
- **Bring every handwritten file back under 500 lines.** Baseline 2026-09-02: **44**
  production and **27** test Python files over, plus **10** handwritten frontend files.
  Counted over git-tracked handwritten sources only — no `migrations/`, and on the
  frontend no `generated/` or `routeTree.gen.ts` — so the number can be re-derived
  rather than trusted.
  The largest are `apps/job/services/job_service.py` (3,044), `apps/job/api.py` (1,863)
  and `apps/job/services/workshop_pdf_service.py` (1,582); **19** handwritten files
  exceed 1,000 lines (18 Python, 1 frontend). Four passes: inventory plus a CI gate
  admitting no new offenders; split
  everything over 1,000 lines; split the rest; split the test files by behaviour under
  test. Generated files stay exempt. Line count says *where* to decompose, never *how*:
  moving line ranges into vaguely named helpers satisfies the number and preserves the
  defect. Related: [KAN-259](https://docketworks.atlassian.net/browse/KAN-259).
- **The three cost-line endpoints must set the job ETag on their own responses.** Create,
  patch and delete cost line (`apps/job/api.py`) each bump the job's `updated_at` through
  `_update_cost_set_summary`, which is what the job ETag is derived from, but none of them
  calls `_set_job_etag(response, job_id)`. The client therefore has to refetch `getFullJob`
  after every settled cost-line write purely to re-arm the etag store the header's If-Match
  reads (`features/job/invalidateJobViews.ts`). The server change alone does not land it:
  cost lines live at `/api/job/cost_lines/{id}/`, and the concurrency interceptor's job
  rule captures a version only from `/api/job/jobs/` URLs and reads the job id out of the
  URL path (`isVersionedEndpoint` and `jobIdFromUrl` in
  `src/lib/concurrency/interceptors.ts`), so a header set on a cost-line response is
  discarded. Pair the three `_set_job_etag` calls with teaching the interceptor those URLs
  — the job id from the response body, or an `X-Resource-Id` beside `X-Resource-Version`.
  Until both land, the `getFullJob` refetch stays. Once they do, a cost-line write needs
  only the cost-set and timeline keys, and `features/timesheet/useTimesheetEntries.ts` —
  which writes cost lines against arbitrary jobs and cannot reach across features to
  invalidate job views — stops being a hole that 412s the next header edit.
- **`getFullJob` returns more than any consumer reads.** `get_job_for_edit`
  (`apps/job/services/job_service.py`) returns every `JobEvent` for the job unpaginated,
  and `job_detail_data` embeds `latest_estimate`, `latest_quote` and `latest_actual` as
  whole cost sets with their lines — which no frontend consumer reads, since the costing
  tabs fetch cost sets by their own endpoint. Drop the embedded cost sets and page the
  events. This is on a hot path: the response is refetched after every settled cost-line
  write. [KAN-324](https://docketworks.atlassian.net/browse/KAN-324) covers the wider
  question of how many ways a cost set's total is computed, and should be settled with it.
- **`companies_jobs_retrieve` is unpaginated and feeds the link-job picker.**
  `apps/company/api.py` returns every job a company has ever had, and
  `PhoneCallLinkJobDialog` fetches it to populate the job list. A company with thousands of
  jobs sends a response past the 100 KB E2E wire guard and past what a picker can usefully
  render. Page it, or cap it server-side to the newest jobs the picker offers.
- **The E2E network log records a negative request duration.** `enableNetworkLogging` in
  `frontend/tests/e2e/helpers.ts` writes `duration_ms` as
  `timing.responseEnd - timing.startTime`, but Playwright's `startTime` is an epoch
  millisecond value while `responseEnd` is an offset from it, so every row is a large
  negative number. The `>= 0` guard added since only rejects the `-1` sentinel — both real
  values pass it. Log `responseEnd` directly.
- **Teach the outbound-link probe to verify Google place ids.** Both
  `SupplierPickupAddress.google_place_id` and `CompanyDefaults.google_place_id` are excused
  as unverifiable, which stopped being true when `apps.core.geocoding.fetch_place` landed:
  re-reading a place by its id is the check. Needs a `google_place` link kind, a pooled
  adapter beside the Google Drive one, and enumeration wiring.
- **Read-side fallback cleanup**
  ([KAN-338](https://docketworks.atlassian.net/browse/KAN-338)). ~40 reads of our own JSON
  shapes violate ADR 0015/0028/0045, concentrated in JSONField payloads mypy cannot see
  into. The `is_billable` divergence between timesheet aggregation and the shop-job
  validator is the priority — billing math that can already disagree on real rows.
- **Scrubber policy: exactly PII, exactly once**
  ([KAN-341](https://docketworks.atlassian.net/browse/KAN-341)). The production-host scrub
  is the single confidentiality transition; downstream data is non-confidential by
  construction and is never re-scrubbed. KAN-341 carries the field inventory and a
  completeness gate over ALL apps — the pay-slip leak lived in exactly the blind spot a
  hand-scoped model list leaves.
- **A client error IS an AppError — invert the rule.** 422s already persist;
  service-level client errors must too. Twelve assertions across six files invert, and
  ADR 0019 records the reasoning. Do the retention item with it.
- **AppError retention: 90 days resolved, 365 unresolved.** Nothing deletes one today, and
  the size driver is the `data` JSONField holding a full traceback.
- **WIP report: bound invoices by the report date, and stop dropping unbilled jobs from
  the cost view.** Both halves change reported numbers on the day they ship, so they need
  a behaviour-ledger entry and someone telling whoever reads the report. See open
  decision 2.
- **Response nullability** shrinks per slice, not in a sweep: when a slice ports a screen,
  the schemas that screen reads declare `| None` only where the producing service can
  return `None`. The count is in `code-quality.md`.
- **`X | None` returns** — the *Optional returns* row of `code-quality.md`. ADR 0045 binds
  new code; the existing sites are a sweep.
- **Ratify every AI-argued ADR exception with the owner**
  ([KAN-342](https://docketworks.atlassian.net/browse/KAN-342)). ADR 0051 makes a
  model-originated rationale an unratified claim, so the codebase carries exceptions to its
  own ADRs that no human signed off. **Do the rule-level rulings first — that is what makes
  this days rather than months:** DJ001, PLC0415 and E402 are 59% of all suppressions and
  look like one policy each (ADR 0040; the deliberate call-time-import pattern; Django-setup
  ordering). Sites carrying no written reason at all are worse than an AI-written one, which
  at least states a claim that can be tested; most sit inside those three and clear with the
  rulings, leaving chiefly BLE001 and C901 to read one at a time. S603, the
  security-sensitive rule, has zero unreasoned sites.
- **Purge "v1" and "v2" from comments, docstrings, docs, ADRs and filenames.** We document
  state, not change: "v1 silently substituted the company default; v2 raises" becomes "a
  staff member without a wage rate cannot be costed". Delete first, reword only what states
  a live invariant. Scope includes this file, the cutover checklist, the behaviour ledger,
  the `db_table = "workflow_*"` overrides, `scripts/v1-frontend-operations.yml`,
  `export_openapi.py`'s `DISSOLVED_V1_APPS` and `status_table.py`'s port rows. The
  port-progress machinery cannot go until the operations it counts are ported or dropped.

## Seams left inside completed slices

Each has a loud marker in code — `grep -rn "Phase 4\|Phase 5\|SEAM" apps/` — listed so
they are not rediscovered by accident: Xero-synced company update and
`Company.get_company_for_xero`; PDF price-list extraction (the browser layer is tested
against a fake WebDriver, but whether the selectors still match the live portal cannot be
tested locally — validate with the Steel & Tube run under Operations);
`update_completion_checklist`; purchasing re-receipting, which deletes prior stock while
still accumulating `received_quantity` and needs a deliberate stock-reconciliation
decision; the PO detail, timesheet grid and costing grid seam lists; and the data-versions
subscription, live for kanban only, which other surfaces join as they arrive (ADR 0047) —
never a second stream.

## Engineering backlog

- **[KAN-357](https://docketworks.atlassian.net/browse/KAN-357): rebuild v2 as a clean
  modular monolith.** Dissolve `apps.core` — today one module holds `AppError`,
  `IntegrationSettings`, `CompanyDefaults` and `ServiceAPIKey` — and replace the
  colon-separated domain tier with enforced context boundaries. **Gated on its own first
  item:** it overturns the layout CLAUDE.md documents, so nothing starts before the
  owner-ratified ADR exists. Scoping caution recorded on the ticket: the draft justified
  the work as breaking seven ORM cycles, but a full traversal of the app registry finds
  exactly one (`accounts` <-> `job`, via `Staff.default_labour_subtype`); the rest are
  one-way and several already point where the target architecture wants them. The value is
  ownership and enforceable boundaries, not cycle removal.
- **Call-recording retention is a setting, not a literal** (owner, 2026-08-23). Two knobs:
  the provider-side deletion delay, a literal 31 days at
  `apps/crm/services/phone_call_service.py:187`, becomes
  `IntegrationSettings.phone_provider_recording_deletion_after_days` beside its switch; and
  local retention, which does not exist — archived recordings under
  `PHONE_RECORDING_STORAGE_ROOT` are kept forever — becomes
  `CompanyDefaults.phone_recording_retention_days` (default 730) with a beat task that
  deletes the file and its `PhoneCallRecording` row past the cutoff by call date, refuses to
  run while the value is unset, and ships with a spec because it destroys data.
- **No timeout, retry or spend cap at the LLM boundary.** litellm's default
  `request_timeout` is 6000s, so a hung vendor pins a worker for 100 minutes. ADR 0041
  claims the gateway is where these live; make that true.
- **Rename what v1 misnamed.** The known instance is the sales forecast, which forecasts
  nothing — it reconciles Xero invoice totals against job revenue attribution for months
  already past. Sweep for the others rather than fixing only this one; ADR 0017 settles
  how far each rename has to reach.
- Port v1's kanban search-ranking test net (~30 tests); the scoring code is line-identical
  but v2's regression net is 4 tests.
- **E2E harness: sync-window open/close** (seam comment atop `global-setup.ts`) is unbuilt —
  only the sync loop consumes it, and kanban waits on its own board. v1's rich login
  diagnostics are debugging aids, not blockers; port them if a flaky login ever needs them.
- CRM wire-pin tests (portal login/CDR form fields, `b"200"` strip, `Result == "1"`,
  timeouts) and superuser-gate tests on recording deletes.
- **The kanban board has no non-drag way to change a job's status on desktop** — the card's
  status button is `lg:hidden`, a WCAG 2.1 SC 2.5.7 defect. Fix with
  pragmatic-drag-and-drop's documented action-menu alternative, not a hand-rolled shortcut
  layer. Until then the job-detail header is the non-pointer path.
  [KAN-327](https://docketworks.atlassian.net/browse/KAN-327) asks for the same right-click
  affordance from the business side.
- Unify invalid-state handling across document managers: the invoice manager raises
  `ValueError` for "job already paid" (a 500 via the envelope) where the quote sibling
  refuses with readable 400 values. Include the provider.
- **Rewrite the known-weak tests** rather than leaving green-but-meaningless assertions
  (ADR 0052): `test_price_extraction.py:48,:59` assert docstring headings and the
  no-vendor-SDK grep misses `from mistralai import` — AST it or use an import-linter
  contract; `test_llm_client.py:195` is constant == constant;
  `test_stock_metadata_tasks.py:102-155` mocks the unit under test;
  `test_products_are_saved_in_batches_during_a_long_run` is vacuous; and
  `test_a_mapping_with_no_item_code_is_simply_not_in_xero` is tautological.
- Untested paths worth a net: the per-row savepoint in `save_products`, `_save_mapping`'s
  concurrent-parse branch, `scheduled_task_service.py`'s malformed-entry guards, and
  `MAX_FAILURE_RATIO`'s 50% boundary.
- **Fixture renderers pass secrets as process arguments.** All three
  `scripts/server/instance.sh` renderers (`render_ai_providers_fixture`,
  `render_xero_apps_fixture`, `render_integration_settings_fixture`) expand API keys, the
  Xero client secret and the phone password into `sed -e` arguments, readable by any local
  user listing processes while provisioning runs. Render through one helper that reads
  values from stdin, for all three at once.
  [KAN-337](https://docketworks.atlassian.net/browse/KAN-337) is the same defect in the
  certbot DNS hooks — one ruling should cover both.
- **Rule on `exclude_type_checking_imports`.** It sits inside the layers contract table in
  `pyproject.toml`, where import-linter 2.13's `LayersContract` appears to ignore it — the
  gate currently refuses even TYPE_CHECKING-only imports across layers (stricter than
  configured, so no hole, but the config line claims a behaviour the gate does not deliver).
- **The time-pair/hours agreement holds per write path, not per row.** The workshop
  endpoints refuse an inconsistent trio and `CostLine.meta` now refuses non-clock time
  strings, but the cost-line grid endpoints can still change `quantity` on a line whose meta
  carries a start/end pair — the my-time calendar then draws a block whose size and title
  disagree. The fix is the same validation in `CostLine.clean` for time lines, plus a
  decision about what the office grid (which has no time fields) should do to a timed line's
  pair when it edits hours.
- `to_optional_decimal` has a sibling `_decimal_or_none`
  (`crm/services/phone_call_service.py:1078`) with no `is_finite()` check, writing
  `Decimal("NaN")` into the call `charge` money column.
- **Six unrecorded API deviations** to ledger or fix, including `render_schedule` strings
  and search not implementing DRF's token splitting (`?search=entry apps.job` → v1 120 rows,
  v2 **0**). [KAN-335](https://docketworks.atlassian.net/browse/KAN-335) extends
  `schema_parity_diff.py` to see property types, which is the instrument that should have
  caught these.
- **Docstrings asserting behaviour the code does not implement**: the beat-wiring advice and
  the litellm stub's justification. `is_discontinued`'s `help_text` lies — make the flag mean
  something or drop it.
- **Service TypedDicts declaring `str` ids whose wire mirror says `UUID`** — five in
  `apps/company/services/duplicate_identity_report.py`. The parity diff cannot see this class
  today, which is exactly what
  [KAN-335](https://docketworks.atlassian.net/browse/KAN-335) fixes; do them together rather
  than reading each app's `services/*.py` against its `schemas.py` by hand.
- **PO `reference` should be `NullableText`, not a service coercion**
  ([KAN-330](https://docketworks.atlassian.net/browse/KAN-330)). The production 500 the
  ticket opens with was a v1 defect and died at cutover; what survives is that
  `purchase_order_service.py` coerces blank to `None` in the service, the pattern ADR 0040
  forbids. Declare it at the boundary, drop the two coercions, regenerate the client.
- **Three defects the handler-gate annotation surfaced**, deferred so a behaviour change
  would not ride a test-gate PR: `time_entry_rates.py` (`to_decimal` maps an unparseable
  stored multiplier to the default — absent keeps the default, present-but-unparseable
  should raise; 0 malformed of 13,931 rows); `phone_call_service._positive_int`
  (`float("inf")` passes the isinstance gate and `int()` raises OverflowError);
  `job.py has_quote` (catch `ObjectDoesNotExist`, not bare `AttributeError`).
- **PR #26's final commit `72a7118` was never reviewed** (CodeRabbit rate limit). It closes
  four holes in the handler gate, and three earlier rounds each found real holes in that same
  file — re-review `config/tests/test_exception_handler_contract.py` when the fixes above
  touch it.
- Timesheet-entry leftovers, both inherited and neither spec-asserted: a draft's stale
  `labour_subtype` surviving a job repick can make `rateForSubtype` throw (v1 misbehaves too,
  so unifying needs a decision); `SmartTimesheetTable`'s focus handoff queries `document`
  rather than the grid's root.
- **The nav menu needs two clicks to reopen** after an unsaved-changes guard refuses a
  navigation started from it. Radix toggles the trigger on pointerdown and the guard's
  synchronous `window.confirm` leaves that toggle out of step with the unmounted content.
  Only the leave-settings E2E reproduces it; seam comment on `NavMenu` in
  `features/shell/AppNavbar.tsx`.
- Cosmetic: `base.py` fetches all known URLs then discards them when `refresh_old`;
  `scheduled_task_service.py`'s unreachable-false guard; `llm_client.py` truthiness-tests a
  `str | None` and sets a module global on every call.

## Open decisions — need YOUR answer

1. **Cost-line write auth is looser than the timesheet reads.** The management reads are
   superuser-only because they expose wage data, but the write path the entry grid uses is
   plain authenticated: `job_jobs_cost_sets_actual_cost_lines_create` accepts an arbitrary
   `staff` UUID with no ownership check, and cost-line PATCH/DELETE are likewise open — so
   any authenticated staff member can attribute, edit or delete a colleague's time line,
   bypassing the ownership rule the self-service endpoints enforce.
   `job_jobs_cost_sets_retrieve` also serves every time line's wage-loaded `unit_cost` to
   any staff. Your call whether writes gate on office/superuser, or on ownership.
2. **WIP report "as at" semantics.** For a historical `date=` the cost side is bounded by
   the report date but the invoiced amount is not (v1 identical), so invoices issued after
   the report date reduce historical net WIP; and the `total_rev == 0` inclusion gate drops
   cost-only jobs from the `method=cost` view (v1 identical). Both are faithful ports whose
   fix changes report numbers.
3. **Two my-time rulings to ratify (ADR 0051).** (a) `timesheets_jobs_retrieve` is now
   self-service so the workshop job picker works for its own audience — which shows every
   staff member per-job charge-out `labour_rates`, `estimated_hours` and the whole-table `q`
   search, not just the four fields the picker reads. The ledger records the change; the
   wage rule is untouched. (b) The my-time page navigates to and books weekends regardless
   of `weekend_timesheets_enabled` (v1 identical), while the office entry page cannot reach
   a weekend date with the flag off. Say whether workshop self-service should honour the
   flag.

## Constraints that cost a day if rediscovered

Not tasks. Each is invisible until it burns a slice.

1. **Most specs build their test data by driving the browser** (`AppNavbar-create-job` →
   `/jobs/create` → `CompanyLookup` → `PersonSelectionModal` → submit), not by seeding over
   the API. That flow is built; the constraint holds for any spec whose fixture drives it.
2. **Every `console.error` fails a test.** The guard is on in `tests/e2e/fixtures/auth.ts`.
   New code routes TanStack Query error logging and React error boundaries to toasts, or
   brings a per-spec whitelist.
3. **Generated types are camelCase** (`user.fullName`), and the generated TanStack exports
   are *option factories*, not hooks — `useQuery(fooOptions({ path: { id } }))`.
4. **`maxFailures: 1` plus 11 `test.describe.serial` files** means one early failure hides
   most of the suite twice over. Raise it on the CLI when triaging: `--max-failures=10`.
5. **Six specs touch a live Xero tenant** — `company-defaults` test 3, `crm/people`×2
   setup, `create-job-with-new-company`, `job-xero-invoice`, `job-xero-quote`,
   `timesheet/weekly-payroll`. Teardown waits `PRE_RESTORE_XERO_SETTLE_MS = 90_000` before
   restoring. Only `weekly-payroll` writes to payroll, and those tests are opt-in
   (`@xero-payroll-write`, ADR 0050).
6. **`timesheet/performance.spec.ts` asserts wall-clock budgets** — a query waterfall fails
   it even when the page is correct.
7. **One seed constant gates the shared-fixture specs:**
   `TEST_COMPANY_NAME = 'ABC Carpet Cleaning TEST IGNORE'` (`helpers.ts`).
8. **v1 is shadcn-vue** (new-york, slate, lucide), a port *of* shadcn/ui React, so
   `npx shadcn@2 add` reproduces the same class strings **and the same `data-slot`
   attributes the specs assert on**. Same for `vaul-vue` → `vaul` and `vue-sonner` →
   `sonner`. **Install the primitives; never write them.** Still missing: a date library
   and `quill` (specs assert `.ql-editor`). Needed by no spec, so do not port:
   `pdf-vue3`, `@unovis`, `vue-advanced-chat`. (`rrweb` arrived with session replay and
   is off that list.) The v1 source is the archived private repository
   `corrin/docketworks_v1`, not a sibling checkout.
9. **`JobViewTabs.vue` static-imports all ten job tabs**, so a faithful port drags in
   `SafetyWizardModal`, `McpToolDetails`, Quill, `CameraModal` and the
   Quote/History/QuotingChat/Safety/Pdf tabs — 3,100 v1 lines no spec touches. Lazy-route
   them behind stubs.
10. **Formatting in the backend is a bug** — the wire carries numbers and the frontend
    formats (ADR 0046). A schema declaring `str` for a quantity is the review smell.
11. **Confirm a call site exists before porting anything.** v1 exposes operations with zero
    call sites in its own frontend — dead surface no spec can ever verify.
