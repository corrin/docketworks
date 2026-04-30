# Knowledge Map — docketworks
> 112 notes · 18 decisions · 10 open questions · 2026-04-16 → 2026-04-28

> **AI Primer:** This knowledge base spans 2026-04-16 to 2026-04-28 (112 notes). Key topics: alternatives considered, tips, steps, what youll need. Most recent decision: Introduce `AlreadyLoggedException` in `apps/workflow/exceptions.py` that wraps an original exception plus the `AppError.…. 10 open questions remain.

## Key Decisions (18)
- Introduce `AlreadyLoggedException` in `apps/workflow/exceptions.py` that wraps an original exception plus the `AppError.id` it was persisted under. Every exception handler becomes a two-arm pattern: re-raise `AlreadyLoggedException` unchanged; catch anything else, persist once, wrap in `AlreadyLoggedException`, re-raise. `persist_app_error()` returns the `AppError` instance (previously returned `None`) so callers can carry the id forward. Roll out in phases: foundation (exception class + scheduler coverage) → integration layer → service layer → view layer → other entry points.
- Two layers. An **identity layer** (non-blocking) that reads either cookies (always) or, when `ALLOW_DEV_BEARER=true` and the host matches `DEV_HOST_PATTERNS`, a short-lived HS256 bearer signed with `DEV_JWT_SECRET` — on failure it does nothing, remaining anonymous. A **global gate** (blocking) that runs on every request: if not authenticated and the path is not in `AUTH_ANON_ALLOWLIST`, return `401 JSON` for `/api/**` or `302 /login` for everything else. The gate is authoritative; views do not rely on per-view decorators. PROD has `ALLOW_DEV_BEARER=false`, so bearer is ignored even if presented.
- GET endpoints return an `ETag` header derived from `updated_at` (plus the primary key for delivery-receipt endpoints). Mutating endpoints (`PUT`, `PATCH`, `DELETE`, and the domain-specific POSTs — add event, accept quote, process delivery receipt) require `If-Match` with the latest ETag. Missing header → `428 Precondition Required`. Mismatch → `412 Precondition Failed`. The check happens inside the service layer under `select_for_update`, so the comparison and the write are atomic. GETs accept `If-None-Match` for `304 Not Modified`. CORS is configured to expose `ETag` and allow `If-Match` / `If-None-Match` so a cross-origin frontend can participate.
- Every `PUT`/`PATCH` to a Job must submit a delta envelope: `{change_id, actor_id, made_at, job_id, fields, before, after, before_checksum, etag}`. The backend recomputes `before_checksum` over the canonical serialisation of the named fields and rejects the request if it doesn't match the current DB state. Canonicalisation is the shared `compute_job_delta_checksum` function (sorted field keys, `__NULL__` sentinel for `None`, trimmed strings, decimals normalised, dates ISO-8601-UTC with millisecond precision) mirrored in both Python and TypeScript. Rejected envelopes are persisted to `JobDeltaRejection` for diagnostics. Accepted deltas write a `JobEvent` with `delta_before`, `delta_after`, `delta_meta`, `delta_checksum` — enough to support `POST /jobs/{id}/undo-change/` which generates the reversing envelope server-side. `If-Match` from ADR 0003 is still required.
- Drop the JSON response-format enforcement entirely. For each mode define an "emit" tool — `emit_calc_result`, `emit_price_result`, `emit_table_result` — whose parameter schema *is* the mode's output schema. The model's terminal action is to call the emit tool with the final result; tool arguments are already JSON, already validated by Gemini against the declared schema. In `PRICE` mode the model can still call catalogue tools (`search_products`, `get_pricing_for_material`, `compare_suppliers`), and the controller loops, executing them and feeding responses back, until the model calls the emit tool or hits the retry cap.
- Enforce three rules for all REST endpoints: (1) identifiers live in the URL path, never in request body or query string; (2) request bodies contain only data, never identifiers; (3) one endpoint per operation — no conditional routing inside a view. For Job Files this collapses six patterns into three: `JobFilesCollectionView` at `/jobs/{job_id}/files/` (POST upload, GET list), `JobFileDetailView` at `/jobs/files/{file_id}/` (GET, PUT, DELETE), `JobFileThumbnailView` at `/jobs/files/{file_id}/thumbnail/` (GET) — six unique `operationId`s, no collisions, UUID in path for file ids. Old endpoints return `404`; breaking the frontend is intentional and forces migration to the clean shape.
- Implement as a service layer (no REST/UI yet). `PayrollSyncService.post_week_to_xero(staff_id, week_start_date)` categorises the week's `CostLine`s into four buckets by `Job.get_leave_type()`: **work** → Timesheets API with `wage_rate_multiplier → earnings_rate_id` mapping; **other leave** (paid, no balance) → Timesheets API; **annual/sick** → Employee Leave API, grouping consecutive days into `LeavePeriod` objects; **unpaid** → discarded (no posting). Before posting work hours, delete existing timesheet lines to make re-posting idempotent. Before any posting, verify the pay run is `Draft` (not `Posted`) and fail fast with a clear error if locked. Leave-type IDs and earnings-rate IDs are stored on `CompanyDefaults` (seven new fields) and seeded via `python manage.py xero --configure-payroll`.
- Use `git subtree add --prefix=frontend` to import the frontend repo into `frontend/`. Full history is preserved, no submodule gymnastics, no special clone step for contributors. Consolidate config at the root: merge `.gitignore`, fold frontend CI jobs into the root `ci.yml`, combine dependabot ecosystems (`pip` at root, `npm` under `/frontend`, `github-actions` at root), delete the frontend's separate `cd.yml` (root `deploy.sh` builds both), keep genuinely frontend-specific config (`.editorconfig`, `.prettierrc.json`, `.nvmrc`, `frontend/CLAUDE.md`, `frontend/.env.example`) in `frontend/`. Replace the old `simple-git-hooks` + husky setup with a `frontend-lint-staged` hook inside the root `.pre-commit-config.yaml` so there's one pre-commit toolchain.
- Frontend tooling resolves the backend `.env` by convention: it's always `../.env` relative to the frontend directory. Read `APP_DOMAIN` from there and derive the frontend URL (`https://${APP_DOMAIN}`) and allowed hosts at build/run time. Remove the three duplicated vars from `frontend/.env`, `frontend/.env.example`, the server instance template, and `env.d.ts`. Frontend `.env` keeps only the genuinely-frontend-only values: `VITE_UAT_URL` (admin-menu link), `VITE_WEEKEND_TIMESHEETS_ENABLED` (feature flag), E2E test credentials, Xero OAuth test credentials. `vite.config.ts` reads `APP_DOMAIN` inline (not via `db-backup-utils.ts`) to avoid a dependency from build tooling to test tooling.
- One script: `scripts/deploy.sh`, invoked both by the CD pipeline and by a systemd startup service. It runs as the application user, with `sudo` configured via sudoers for the specific `systemctl restart` commands it needs — no user switching, no root-level orchestration. Environment is detected by hostname (`msm` → PROD, `uat-scheduler` → SCHEDULER, `uat`/`uat-frontend` → UAT) rather than by inspecting paths. The script is idempotent so the same code path handles "fresh deploy from CD" and "machine just booted, catch up to `main`." CD runs against both machines with `continue-on-error: true` on the frontend/backend target so a cold second machine doesn't fail the pipeline — the startup service will catch up when the machine comes online.
- Commit codesight output to git and regenerate it via pre-commit. Two hooks in `.pre-commit-config.yaml`: one runs `npx codesight --wiki` and stages `.codesight/`; the other runs `npx codesight --mode knowledge -o docs/.codesight` and stages `docs/.codesight/`. Always use `--wiki` (makes it the default via `codesight.config.json`) because the CLAUDE.md flow reads targeted ~200–300-token articles, not the monolithic `CODESIGHT.md`. Drop the separate `frontend/.codesight/` scan — the root scan already picks up 181 frontend components, so a second scan duplicates work and creates two sources of truth; gitignore `frontend/.codesight/` to prevent accidental commit. `.codesightignore` excludes generated files (`frontend/schema.yml`, `frontend/src/api/generated/`), build artifacts, and `docs/.codesight/` (which has its own scan).
- Strategy pattern, registry-resolved at request time: `apps/workflow/accounting/provider.py` defines `AccountingProvider` (Protocol) covering auth, contacts, documents, sync-pull, and optional capability flags (`supports_projects`, `supports_payroll`). `apps/workflow/accounting/registry.py` exposes `get_provider()`, which reads `settings.ACCOUNTING_BACKEND` (default `"xero"`) and returns the active instance. `apps/workflow/accounting/types.py` defines provider-agnostic payload dataclasses (`InvoicePayload`, `QuotePayload`, `POPayload`, `DocumentResult`) so `xero_python` types stay inside the Xero provider. Keep all existing `xero_*` model fields — they have data and migrations; MYOB installations simply leave them null. Add `CompanyDefaults.accounting_provider` to track which backend is active. Phase the rollout: (1) interface + thin Xero wrapper over existing code, (2) document managers build generic payloads, (3) client service calls `get_provider()`, (4) sync layer becomes provider-agnostic, (5) build MYOB provider.
- Return the underlying exception message in API error responses. Do not mask or generalise exception text for information-hiding reasons. Continue to include the persisted `AppError.id` as `details.error_id` so any response can be cross-referenced with structured logs and the DB row.
- For `if` statements with non-trivial control flow, include an explicit `else` branch. The `else` body can be:
- When a consumer's invariant is violated by stored data, fix the data. In order of preference: (1) data migration that reconstructs the canonical field from another in-row source already populated by an earlier migration, (2) emission-side patch that closes the path producing wrong data going forward, (3) both. The consumer stays strict — no `COALESCE`, no `or detail.changes…`, no schema relaxation, no "tolerant" reads. If the data cannot be reconstructed (the source is genuinely lost), escalate — raise, alert, leave the row visibly broken — rather than silently degrade. Document the unrecoverable subset as out of scope and treat its existence as a separate emission-audit task, not as a reason to relax the contract.
- What we chose, stated as an imperative. One paragraph.
- *Merge `fix/timezones` as-is. Defer the schema promotion until a concrete
- /usr/local/lib/nodemodules/ VS your user account using ~/

## Open Questions (10)
- when we discover data that *is* malformed, what do we do? The temptation is always to make the consumer tolerant ("just
- 3.  **Database:** Is PostgreSQL running? Do credentials in `.env` match the `CREATE ROLE` command?
- 4.  **Migrations:** Run `python manage.py migrate`. Any errors?
- 5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
- is enough approved work flowing into the shop, and if not, where is the bottleneck? The report must be reproducible hist
- when is each job expected to start?
- when is each job expected to finish?
- where are jobs overlapping in time?
- which jobs are late?
- how does work actually flow across the upcoming days?

## Recurring Themes
alternatives considered · tips · steps · what youll need · what happens next · purpose · troubleshooting · prerequisites · verification · acceptance criteria · notes for the implementer · out of scope

## People
@login_required · @extend_schema · @docketworks · @morrissheetmetal · @msm · @property · @github · @bairdandwhyte · @vue · @deprecated · @latest · @playwright · @staff_member_required · @update · @input · @change · @blur · @dataclass · @ljharb · @mhart

## Hub Notes (most referenced)
- `docs/initial_install.md` — **5** incoming references — Initial Installation Guide
- `docs/restore-prod-to-nonprod.md` — **3** incoming references — Restore Production to Non-Production
- `docs/client_onboarding.md` — **2** incoming references — Client Onboarding
- `docs/development_session.md` — **2** incoming references — Development Session Startup
- `docs/server_setup.md` — **2** incoming references — Server Setup
- `restore/extracted/usr/local/nvm/GOVERNANCE.md` — **2** incoming references — `nvm` Project Governance

## Note Index (112)

### Decision Records (16)
- `docs/adr/0001-exception-already-logged-dedup.md` — Wrap once-persisted exceptions in `AlreadyLoggedException` so nested handlers pass through without creating duplicate `AppError` rows, and force scheduler jobs …
- `docs/adr/0002-auth-gate-global-allowlist.md` — A blocking middleware gate rejects any request that is neither authenticated nor on the `AUTH_ANON_ALLOWLIST`; identity comes from cookies in all envs and, in D…
- `docs/adr/0003-etag-optimistic-concurrency.md` — Every Job and PO mutation requires an `If-Match` header carrying the latest ETag; the server rejects mismatches with `412` and missing headers with `428`, atomi…
- `docs/adr/0004-job-delta-envelope.md` — Clients submit a `{change_id, fields, before, after, before_checksum, etag}` envelope for every Job update; the backend re-canonicalises, verifies the checksum,…
- `docs/adr/0005-emit-tools-pattern.md` — Each quote-chat mode terminates by calling an `emit_<mode>_result` tool whose parameter schema *is* the mode's output schema — sidestepping Gemini's tools-vs-JS…
- `docs/adr/0006-rest-resource-hierarchy.md` — Identifiers live in the URL path (not body or query); request bodies carry data only; one endpoint per operation — no conditional routing inside views.
- `docs/adr/0008-frontend-subtree-merge.md` — Pull the frontend repo into `frontend/` via `git subtree add` so backend + frontend share one history, one CI, one deploy script, and one PR for any cross-cutti…
- `docs/adr/0009-env-consolidation-app-domain.md` — Frontend build and test tooling reads `APP_DOMAIN` from the backend `.env` (resolved by convention at `../.env`) and derives URLs + allowed hosts from it — elim…
- `docs/adr/0010-single-deploy-script.md` — One `scripts/deploy.sh` handles PROD, UAT, and SCHEDULER via hostname detection; CD runs it against both UAT machines in parallel with `continue-on-error`, and …
- `docs/adr/0011-codesight-precommit-wiki.md` — Commit `.codesight/` and `docs/.codesight/` to git and regenerate both on pre-commit via `--wiki` and `--mode knowledge` so AI-assistant context never drifts fr…
- `docs/adr/0012-accounting-provider-strategy.md` — Introduce an `AccountingProvider` protocol with per-backend implementations (Xero today, MYOB next) resolved at request time via `get_provider()` — runtime poly…
- `docs/adr/0013-error-message-clarity-over-info-hiding.md` — Internal-tool error responses include the underlying exception message verbatim so the user on the other end can act on it; we rely on authenticated-session log…
- `docs/adr/0014-explicit-else-branches.md` — `if` statements in non-trivial code paths should have an explicit `else` branch, even when the else body is a no-op or a comment. Makes the state machine legibl…
- `docs/adr/0015-fix-data-not-fallback.md` — When a consumer finds data shaped differently from the model's contract, restore the contract by repairing the data (migration, emission fix, or both) — never b…
- `docs/adr/_template.md` ← 1 refs — One-sentence tagline summarising the decision. Codesight's knowledge index grabs this line as the entry description, so make it informative.
- `docs/plans/we-re-going-in-circles-sequential-gem.md` — The PR is on `origin/fix/timezones`, ready to merge. After protracted

### Specs & PRDs (7)
- `docs/production-mysql-to-postgres-migration.md` ← 1 refs — Every command and its key output must be logged, same as the backup-restore process.
- `docs/test_plans/client_contact_management_test_plan.md` — This test plan covers the new client contact management system that replaces Xero contact syncing with local contact storage.
- `frontend/docs/ZODIOS_REFACTOR_GUIDE.md` — **COMPLETE MIGRATION** from raw Axios + handwritten interfaces to Zodios API client
- `frontend/docs/done/e2e_testing_implementation_plan.md` — This document outlines the implementation plan for adding end-to-end (E2E) regression testing with automated screenshot generation to the Vue + Django workflow …
- `frontend/docs/jobview-delta-control-guide.md` — The backend now requires every `PUT /job-rest/jobs/{job_id}` or `PATCH /job-rest/jobs/{job_id}` call to submit a fully self-contained delta envelope. This docum…
- `frontend/docs/xero-payroll-ui-requirements.md` — **For:** Frontend Vue.js Implementation
- `restore/extracted/usr/local/nvm/ROADMAP.md` — This is a list of the primary features planned for `nvm`:

### Retrospectives (1)
- `docs/plans/steady-sleeping-waffle.md` — The current `frontend/src/views/SalesPipelineReportView.vue` (1,139 lines, 5 sections of equal visual weight, 20+ numbers above the fold) does not answer the qu…

### Meeting Notes (2)
- `docs/adr/0007-xero-payroll-sync.md` — Split a week's `CostLine` time entries into work / other-leave / annual-or-sick / unpaid buckets and post each through the right Xero surface (Timesheets API or…
- `frontend/manual/enquiries/new-customer-call.md` — **When to use:** A new or existing customer calls asking about work they need done.

### Session Logs (1)
- `frontend/manual/end-of-week/weekly-checklist.md` — **When to use:** End of the week admin procedures -- making sure nothing's fallen through the cracks.

### General Notes (85)
- `docs/plans/2026-04-28-leave-entries-csv-input.md` — 2026-04-28 — **Trello:** https://trello.com/c/UsstYu5I
- `docs/plans/2026-04-28-utc-localdate-sweep.md` — 2026-04-28 — Eliminate a class of subtle "off by one day" bugs caused by calling `.date()` on
- `docs/plans/2026-04-16-sales-pipeline-report.md` — 2026-04-16 — Build a full `Sales Pipeline Report` that answers one primary question: is enough approved work flowing into the shop, and if not, where is the bottleneck? The …
- `docs/plans/2026-04-16-workshop-schedule-frontend.md` — 2026-04-16 — Build a **calendar-first** Workshop Schedule screen that helps office staff make quick operational
- `docs/plans/2026-04-16-workshop-schedule.md` — 2026-04-16 — Build the backend for an **operations** scheduling feature that helps office staff answer three
- `CLAUDE.md` — This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. `AGENTS.md` is a symlink to this file so Codex, Cursor, a…
- `README.md` — A Django + Vue.js job/project management system for businesses that do lots of small-to-medium jobs for many clients. Originally built for [Morris Sheetmetal](h…
- `docs/README.md` ← 1 refs — DocketWorks is a job/project management system for businesses that do lots of relatively small jobs for many clients — fabrication shops, IT consultancies, trad…
- `docs/adr/README.md` — Short records capturing *why* we chose an approach — the problem, the decision, alternatives ruled out, consequences. Mechanics ("what changed") live in the lin…
- `docs/architecture.md` ← 1 refs — DocketWorks is a Django-based web application that digitizes paper-based workflows from quote generation to job completion and invoicing for businesses that do …
- `docs/client_onboarding.md` ← 2 refs — Everything needed to take a new client from signed contract to running instance. This is the handoff document for the onboarding specialist.
- `docs/development_session.md` ← 2 refs — Steps to start a development session. For first-time setup, see [initial_install.md](initial_install.md).
- `docs/initial_install.md` ← 5 refs — Dev machine setup. One-off steps that persist across restores.
- `docs/instance-setup-demo.md` ← 1 refs — Onboard a prospect for a paid trial of DocketWorks. Uses dummy staff but the prospect's real rates, markups, and configuration. Connects to Xero Demo Company.
- `docs/instance-setup-production.md` ← 1 refs — Set up a production instance for a client connecting to their real Xero organisation.
- `docs/msm-cutover.md` — Move MSM production from the old server (`/home/django_user`, MariaDB, `192.168.1.17`) to the new
- `docs/ngrok_setup.md` ← 1 refs — Set up ngrok tunnels for local development. Do this first — you'll need the domain for Xero app configuration.
- `docs/plans/now-the-performance-concerns-stateful-taco.md` — Two Copilot review comments on #162 flagged the Sales Pipeline service as having hot paths that do Python-side work which could move to SQL:
- `docs/plans/right-let-s-start-implementing-stateful-whisper.md` — Trello card [#276](https://trello.com/c/kEfIg8fA) covers two related JobEvent description bugs spotted in prod, plus a follow-up audit comment. The agreed shape…
- `docs/restore-prod-to-nonprod.md` ← 3 refs — Restore a production backup to any non-production environment (dev or server instance). Assume venv active, `.env` loaded, in the project root.
- _…and 65 more_

---
_Generated by [codesight](https://github.com/Houseofmvps/codesight) v1.10.0_