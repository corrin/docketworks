# Knowledge Map — docketworks
> 214 notes · 14 decisions · 10 open questions · 2026-02-24 → 2026-04-19

> **AI Primer:** This knowledge base spans 2026-02-24 to 2026-04-19 (214 notes). Key topics: verification, files to modify, alternatives considered, tips. Most recent decision: Introduce `AlreadyLoggedException` in `apps/workflow/exceptions.py` that wraps an original exception plus the `AppError.…. 10 open questions remain.

## Key Decisions (14)
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
- What we chose, stated as an imperative. One paragraph.
- /usr/local/lib/nodemodules/ VS your user account using ~/

## Open Questions (10)
- 3.  **Database:** Is PostgreSQL running? Do credentials in `.env` match the `CREATE ROLE` command?
- 4.  **Migrations:** Run `python manage.py migrate`. Any errors?
- 5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
- is enough approved work flowing into the shop, and if not, where is the bottleneck? The report must be reproducible hist
- when is each job expected to start?
- when is each job expected to finish?
- where are jobs overlapping in time?
- which jobs are late?
- how does work actually flow across the upcoming days?
- 1. Which active jobs are likely to miss their promised date?

## Recurring Themes
verification · files to modify · alternatives considered · tips · steps · what youll need · what happens next · troubleshooting · fix · changes · design · purpose

## People
@login_required · @extend_schema · @docketworks · @morrissheetmetal · @msm · @transaction · @pytest · @patch · @classmethod · @rowClick · @resolve · @unresolve · @update · @close · @playwright · @tailwindcss · @vitejs · @cmeconnect · @require_superuser · @can_manage_timesheets

## Hub Notes (most referenced)
- `docs/initial_install.md` — **5** incoming references — Initial Installation Guide
- `docs/client_onboarding.md` — **2** incoming references — Client Onboarding
- `docs/development_session.md` — **2** incoming references — Development Session Startup
- `docs/restore-prod-to-nonprod.md` — **2** incoming references — Restore Production to Non-Production
- `docs/server_setup.md` — **2** incoming references — Server Setup
- `restore/extracted/usr/local/nvm/GOVERNANCE.md` — **2** incoming references — `nvm` Project Governance

## Note Index (214)

### Decision Records (13)
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
- `docs/adr/_template.md` ← 1 refs — One-sentence tagline summarising the decision. Codesight's knowledge index grabs this line as the entry description, so make it informative.
- `docs/plans/1-mechanics-what-synchronous-clover.md` — `docs/plans/completed/` holds 66 finished implementation plans (~9,950 lines). Plans bundle two things:

### Specs & PRDs (31)
- `docs/plans/2026-04-19-admin-errors-dedup-design.md` — 2026-04-19 — **Status:** Design — awaiting user review
- `frontend/docs/plans/2026-03-05-process-documents-frontend-design.md` — 2026-03-05 — Two user-facing experiences built on one backend model:
- `docs/plans/2026-03-03-process-documents-design.md` — 2026-03-03 — Replace the Dropbox `Health & Safety` folder with an in-app document management system. Rename `SafetyDocument` to `ProcessDocument` to reflect broader scope. M…
- `docs/plans/2026-03-03-process-documents-frontend-spec.md` — 2026-03-03 — The backend `SafetyDocument` model has been renamed to `ProcessDocument` with expanded functionality. The frontend needs a new **Process Documents** section tha…
- `docs/plans/CHAT_TESTING_README.md` — Comprehensive testing framework for the chat functionality in the DocketWorks system.
- `docs/plans/chatbot-fix.md` — The frontend now uploads files to jobs and stores file IDs in chat message metadata. The backend needs to extract file IDs from chat history and include those f…
- `docs/plans/completed/BACKEND_CHANGES_COSTLINE_ESTIMATE.md` — Update job creation endpoint to automatically create estimate CostLines based on estimated materials and time.
- `docs/plans/completed/cd_dual_machine_deployment.md` — **Note**: The `deploy_machine.sh` script created by this plan has since been
- `docs/plans/completed/frontend_integration_staff_filtering.md` — The backend has implemented a new staff date-based filtering system that replaces the inconsistent `is_active` boolean field with a proper `date_left` field. Th…
- `docs/plans/completed/job-delta-frontend-integration.md` — The backend now requires every `PUT /job-rest/jobs/{job_id}` or `PATCH /job-rest/jobs/{job_id}` call to submit a fully self-contained delta envelope. This docum…
- `docs/plans/completed/job_quote_chat_plan.md` — The frontend Vue.js app needs Django REST API endpoints to store and retrieve chat conversations for the interactive quoting feature. Each job can have an assoc…
- `docs/plans/completed/job_sheet_additional_fields.md` — Add four new fields to the printed job sheet (workshop PDF):
- `docs/plans/completed/linked_quote_implementation_plan.md` — This document outlines the implementation plan for adding linked quote functionality to the jobs system. The plan breaks down the work into smaller, testable ti…
- `docs/plans/completed/minor_chatbot_tidy_plan.md` — This plan addresses minor coding standard issues identified in the chatbot implementation commits. The implementation is well-structured but needs refinement to…
- `docs/plans/completed/seed_xero_plan.md` — Create a management command to seed Xero development tenant with database clients and jobs. This is needed after production database restore to populate Xero wi…
- `docs/plans/completed/staff_utilisation_plan.md` — Two APIs to support 1:1 performance management - identify lazy staff, time dumpers, and compare individual performance against team averages.
- `docs/plans/completed/xero-payroll-integration.md` — **Updated:** 2025-11-04
- `docs/plans/completed/xero-projects-ticket-1.md` — Adding Xero sync fields to Job, Staff, and CostLine models to support Xero Projects API integration.
- `docs/plans/completed/xero-projects-ticket-2.md` — Changing Invoice model relationship from OneToOneField to ForeignKey to support multiple invoices per job, as required by Xero Projects API.
- `docs/plans/completed/xero-projects-ticket-3.md` — Adding Projects API calls to the existing Xero API infrastructure to support project creation, updates, and time/expense entry management.
- _…and 11 more_

### Meeting Notes (4)
- `docs/plans/completed/2026-04-01-postgres-sequence-sync.md` — 2026-04-01 — E2E tests fail with `IntegrityError` on `workflow_historicaljob_pkey` because the custom `syncSequences` SQL query misses identity column sequences (all SimpleH…
- `docs/adr/0007-xero-payroll-sync.md` — Split a week's `CostLine` time entries into work / other-leave / annual-or-sick / unpaid buckets and post each through the right Xero surface (Timesheets API or…
- `docs/plans/xero-projects-sync-plan.md` — This document outlines the plan to synchronize job data between Morris Sheetmetal's job management system and Xero Projects API.
- `frontend/manual/enquiries/new-customer-call.md` — **When to use:** A new or existing customer calls asking about work they need done.

### Research (1)
- `docs/plans/completed/duplicate-client-bug-investigation.md` — **Problem:** After restore process, found 27 duplicate client names (54 total records).

### Session Logs (1)
- `frontend/manual/end-of-week/weekly-checklist.md` — **When to use:** End of the week admin procedures -- making sure nothing's fallen through the cracks.

### Backlogs (1)
- `docs/plans/xero-projects-tickets.md` — **NEVER mark tickets as DONE (✅) unless ALL sub-tasks are actually completed and working.**

### General Notes (163)
- `docs/plans/2026-04-19-admin-errors-dedup-plan.md` — 2026-04-19 — **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan tas…
- `docs/plans/2026-04-19-fix-xero-client-creation-500.md` — 2026-04-19 — Creating a client via `POST /clients/` returns 500. The Xero contact is created successfully, but response serialization rejects `xero_contact_id` because it co…
- `docs/plans/2026-04-19-predeploy-backup.md` — 2026-04-19 — `scripts/server/deploy.sh` currently does: pull central repo → per-instance `git pull` → shared deps → per-instance build + migrate + restart. There is no safet…
- `docs/plans/completed/2026-04-19-e2e-cleanup-protect-fks.md` — 2026-04-19 — Filename note: the auto-generated plan name doesn't follow the `YYYY-MM-DD-description.md` convention. Rename to `2026-04-19-e2e-cleanup-protect-fks.md` before …
- `docs/plans/completed/2026-04-19-favicon-404-fix.md` — 2026-04-19 — Browsers requesting `https://office.morrissheetmetal.co.nz/favicon.ico` (and every other docketworks instance) get a 404. The favicon file itself is fine — `fro…
- `docs/plans/completed/2026-04-19-fix-client-lookup-option-name.md` — 2026-04-19 — `frontend/tests/job/edit-job-settings.spec.ts:479` uses
- `docs/plans/2026-04-18-extend-schema-explicit-request-body.md` — 2026-04-18 — Naming note: file should be renamed to `2026-04-18-remove-response-serializer-class-from-apiviews.md` (project convention is `YYYY-MM-DD-description.md`). Plan-…
- `docs/plans/2026-04-18-linux-user-underscore-naming.md` — 2026-04-18 — **Goal:** Make per-instance OS user names match the DB role names (both `dw_<client>_<env>`) instead of diverging (`dw-<client>-<env>` vs `dw_<client>_<env>`).
- `docs/plans/completed/2026-04-17-create-missing-xero-items.md` — 2026-04-17 — When restoring prod data to a dev environment, the Xero demo org periodically gets reset. The payroll calendar (e.g. "Weekly Testing") no longer exists in the f…
- `docs/plans/completed/2026-04-17-e2e-backup-lifecycle-fix.md` — 2026-04-17 — The current setup/teardown uses a persistent `.latest_backup` file to track the backup path across runs. This causes two problems:
- `docs/plans/completed/2026-04-17-fix-xero-oauth-cancel.md` — 2026-04-17 — When a user clicks Cancel during Xero OAuth login, Xero redirects back with `?error=access_denied&error_description=...` query params. The callback view ignores…
- `docs/plans/2026-04-16-sales-pipeline-report.md` — 2026-04-16 — Build a full `Sales Pipeline Report` that answers one primary question: is enough approved work flowing into the shop, and if not, where is the bottleneck? The …
- `docs/plans/2026-04-16-workshop-schedule-frontend.md` — 2026-04-16 — Build a **calendar-first** Workshop Schedule screen that helps office staff make quick operational
- `docs/plans/2026-04-16-workshop-schedule.md` — 2026-04-16 — Build the backend for an **operations** scheduling feature that helps office staff answer three
- `docs/plans/completed/2026-04-15-server-setup-apt-consolidation.md` — 2026-04-15 — **Context:** `server-setup.sh` has 10 separate `apt install` calls. Six are unconditional and can be grouped into one block right after `apt update && apt upgra…
- `docs/plans/completed/2026-04-15-server-setup-no-cert-fqdn.md` — 2026-04-15 — **Goal:** Allow `server-setup.sh` to skip SSL cert acquisition, and allow `instance.sh create` to configure nginx for a custom FQDN so cutover day is just: poin…
- `docs/plans/2026-04-12-delivery-receipt-code-review.md` — 2026-04-12 — Reviewing `delivery_receipt_service.py` (431 lines) against the project's defensive programming philosophy: fail early, handle unhappy cases first, no fallbacks…
- `docs/plans/completed/2026-04-12-accounting-abstraction.md` — 2026-04-12 — A customer uses MYOB instead of Xero. Docketworks is single-tenant (one installation per client), so each instance uses exactly one accounting package. We need …
- `docs/plans/completed/2026-04-12-accounting-provider-review-fixes.md` — 2026-04-12 — Code review found the `XeroAccountingProvider` has massive DRY violations, missing `persist_app_error` calls, defensive code that doesn't trust the data model, …
- `docs/plans/2026-04-10-seed-invoices-to-xero.md` — 2026-04-10 — When restoring a production database to dev, Invoice records come with `xero_id` values pointing at prod's Xero tenant. The `xero_id` field is NOT NULL, so we c…
- _…and 143 more_

---
_Generated by [codesight](https://github.com/Houseofmvps/codesight) v1.10.0_