# Knowledge Map — docketworks
> 120 notes · 20 decisions · 10 open questions · 2026-04-16 → 2026-05-01

> **AI Primer:** This knowledge base spans 2026-04-16 to 2026-05-01 (120 notes). Key topics: problem, why, alternatives considered, tips. Most recent decision: `AlreadyLoggedException` (in `apps/workflow/exceptions.py`) wraps the original exception plus the persisted `AppError.id…. 10 open questions remain.

## Key Decisions (20)
- `AlreadyLoggedException` (in `apps/workflow/exceptions.py`) wraps the original exception plus the persisted `AppError.id`. Every handler is two-arm: re-raise `AlreadyLoggedException` unchanged; otherwise persist once, wrap, re-raise. `persist_app_error()` returns the `AppError` instance so callers can carry the id forward.
- Two layers. An **identity layer** (non-blocking) reads cookies always and, when `ALLOW_DEV_BEARER=true` and the host matches `DEV_HOST_PATTERNS`, an HS256 bearer signed with `DEV_JWT_SECRET`. A **global gate** (blocking) runs on every request: not authenticated and path not in `AUTH_ANON_ALLOWLIST` → `401 JSON` for `/api/**`, `302 /login` for everything else. The gate is authoritative; views do not rely on per-view decorators. PROD has `ALLOW_DEV_BEARER=false`, so bearer is ignored even if presented.
- GETs return an `ETag` derived from `updated_at` (plus the primary key for delivery receipts). Mutating endpoints (`PUT`, `PATCH`, `DELETE`, and the domain-specific POSTs) require `If-Match` with the latest ETag. Missing → `428 Precondition Required`. Mismatch → `412 Precondition Failed`. The check happens inside the service layer under `select_for_update`, so comparison and write are atomic. GETs accept `If-None-Match` for `304 Not Modified`. CORS exposes `ETag` and allows `If-Match` / `If-None-Match` so a cross-origin frontend can participate.
- Every `PUT`/`PATCH` to a Job carries an envelope: `{change_id, actor_id, made_at, job_id, fields, before, after, before_checksum, etag}`. The backend recomputes `before_checksum` over a canonical serialisation of the named fields and rejects the request if it doesn't match the current DB state. Canonicalisation is `compute_job_delta_checksum` (sorted keys, `__NULL__` sentinel for `None`, trimmed strings, normalised decimals, ISO-8601-UTC dates with millisecond precision) mirrored bit-identical in Python and TypeScript. Accepted deltas write a `JobEvent` with `delta_before`, `delta_after`, `delta_meta`, `delta_checksum`. Rejected envelopes go to `JobDeltaRejection`. `If-Match` is still required.
- Drop JSON response-format enforcement. Define an emit tool per mode (`emit_calc_result`, `emit_price_result`, `emit_table_result`) whose parameter schema *is* the mode's output schema. The model's terminal action is calling the emit tool; tool arguments are already JSON, already schema-validated by Gemini. In `PRICE` mode the controller loops on catalogue tool calls until the model emits or hits the retry cap (5).
- Three rules for all REST endpoints:
- `PayrollSyncService.post_week_to_xero(staff_id, week_start_date)` categorises entries by `Job.get_leave_type()`:
- Use `git subtree add --prefix=frontend` to import the frontend into `frontend/`. Full history preserved, no submodule init step. Consolidate at the root: one `.gitignore`, one `ci.yml` running both stacks, one Dependabot config covering all three ecosystems (`pip`, `npm`, `github-actions`), one `deploy.sh` that builds both. Genuinely frontend-specific config (`.editorconfig`, `.prettierrc.json`, `.nvmrc`, `frontend/CLAUDE.md`, `frontend/.env.example`) stays in `frontend/`. Replace the old `simple-git-hooks` / husky setup with a `frontend-lint-staged` hook in the root `.pre-commit-config.yaml`.
- Frontend tooling resolves the backend `.env` at `../.env` by convention. Read `APP_DOMAIN` from there, derive frontend URL and allowed hosts at build/run time. Remove the three duplicated vars from `frontend/.env`, `frontend/.env.example`, the server instance template, and `env.d.ts`. `frontend/.env` keeps only genuinely-frontend-only values (feature flags, E2E credentials, OAuth test creds). `vite.config.ts` reads `APP_DOMAIN` inline so build tooling has no dependency on test tooling.
- One script: `scripts/deploy.sh`, invoked both by CD and by a systemd startup service. Runs as the application user, with `sudo` configured via sudoers for the specific `systemctl restart` commands it needs. Environment is detected by hostname (`msm` → PROD, `uat-scheduler` → SCHEDULER, `uat`/`uat-frontend` → UAT). The script is idempotent: same code path handles "fresh deploy from CD" and "machine just booted, catch up to `main`." CD runs it against both UAT hosts with `continue-on-error: true` on the frontend/backend target so a cold machine doesn't fail the pipeline — the startup service catches it up later.
- Two pre-commit hooks in `.pre-commit-config.yaml`: one runs `npx codesight --wiki` and stages `.codesight/`; the other runs `npx codesight --mode knowledge -o docs/.codesight` and stages `docs/.codesight/`. Wiki mode is the default via `codesight.config.json`. `.codesightignore` excludes generated files (`frontend/schema.yml`, `frontend/src/api/generated/`), build artefacts, and `docs/.codesight/` (which has its own scan). Drop the separate `frontend/.codesight/` scan — the root scan already covers frontend; gitignore that path to prevent accidental commit.
- `apps/workflow/accounting/provider.py` defines `AccountingProvider` (Protocol) covering auth, contacts, documents, sync-pull, plus capability flags (`supports_projects`, `supports_payroll`).
- Return the underlying exception message in API error responses. Do not mask or generalise exception text for information-hiding reasons. Always include `details.error_id` so any response can be cross-referenced with structured logs and the `AppError` row.
- For `if` statements with non-trivial control flow, include an explicit `else`. The body can be:
- When stored data violates a consumer's invariant, fix the data. In order of preference: (1) data migration that reconstructs the canonical field from another in-row source; (2) emission-side patch that closes the path producing wrong data going forward; (3) both. The consumer stays strict — no `COALESCE`, no `or detail.changes…`, no schema relaxation, no tolerant reads. If the data genuinely cannot be reconstructed, escalate (raise, alert, leave the row visibly broken) rather than silently degrade. Document the unrecoverable subset as a separate emission-audit task.
- When an ambiguous name is identified, rename everything: model field → migration → serializer → API field → frontend type → grid column → every consumer, end-to-end, in a dedicated rename PR. No grandfathering, no legacy allowlist, no waiting. No fallbacks to the legacy name (no `getattr(obj, 'new_name', obj.old_name)`, no serializer accepting both, no DB column kept "for safety," no aliased re-exports). The rename PR removes the old name in the same commit that adds the new one.
- When something changes, change every caller in the same PR. Old name disappears in the same commit the new name appears. Old URL returns `404`, not a redirect. Old field is removed from the model, not kept null. Old serializer key is removed, not accepted-but-deprecated. Old SDK import path is gone, not re-exported. Tests and CI break loudly on stragglers; that's the point.
- In any non-trivial function, check the bad case first (`if <bad>: handle_error()`) before doing the work for the good case. Validate every required input at the call boundary; raise immediately on missing or malformed values rather than coercing them to defaults. No default values or fallbacks that paper over missing configuration or malformed rows. When the issue is data shape, repair the data (ADR 0015) — do not soften the consumer.
- Every `except` block follows a two-arm pattern. If the caught exception is already an `AlreadyLoggedException` (ADR 0001), re-raise it unchanged — it has been persisted by an inner handler. Otherwise, call `persist_app_error(exc)`, wrap in `AlreadyLoggedException`, and re-raise. `persist_app_error` returns the `AppError` row so the UUID id can be carried forward into the wrapping exception and into API error responses (ADR 0013). The handler re-raises unless business logic explicitly requires continuation. Net effect: every distinct failure produces exactly one `AppError` row, regardless of how many `except` blocks the exception passed through.
- 1. If a value involves the database, business rules, or external systems → **backend**. Frontend reads it as a number/string, never recomputes it.

## Open Questions (10)
- when stored data *is* malformed, what do we do? The temptation is always the one-line read-side fallback ("if `delta_aft
- 3.  **Database:** Is PostgreSQL running? Do credentials in `.env` match the `CREATE ROLE` command?
- 4.  **Migrations:** Run `python manage.py migrate`. Any errors?
- 5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
- is enough approved work flowing into the shop, and if not, where is the bottleneck? The report must be reproducible hist
- Per the policy "users shouldn't have to flip everywhere", the timesheet entry grid's `Wage` column shows one number per row. Which?
- When the staff member has `base_wage_rate = 0` (e.g. admin user, or not yet set), what should the Wage column show?
- | Number | Preempts |
- TZ-aware schema migration first?
- process.env.MSM_FRONTEND_URL ??

## Recurring Themes
problem · why · alternatives considered · tips · what youll need · steps · what happens next · troubleshooting · prerequisites · purpose · verification · out of scope

## People
@login_required · @docketworks · @morrissheetmetal · @msm · @property · @github · @bairdandwhyte · @vue · @deprecated · @latest · @playwright · @staff_member_required · @update · @input · @change · @blur · @dataclass · @ljharb · @mhart · @nvm

## Hub Notes (most referenced)
- `docs/initial_install.md` — **5** incoming references — Initial Installation Guide
- `docs/restore-prod-to-nonprod.md` — **3** incoming references — Restore Production to Non-Production
- `docs/client_onboarding.md` — **2** incoming references — Client Onboarding
- `docs/development_session.md` — **2** incoming references — Development Session Startup
- `docs/server_setup.md` — **2** incoming references — Server Setup
- `restore/extracted/usr/local/nvm/GOVERNANCE.md` — **2** incoming references — `nvm` Project Governance

## Note Index (120)

### Decision Records (22)
- `docs/adr/0001-exception-already-logged-dedup.md` — Wrap once-persisted exceptions in `AlreadyLoggedException`; nested handlers re-raise unchanged instead of re-persisting.
- `docs/adr/0002-auth-gate-global-allowlist.md` — A blocking middleware gate rejects any request that is neither authenticated nor on `AUTH_ANON_ALLOWLIST`. Identity comes from cookies in all envs and, in DEV o…
- `docs/adr/0003-etag-optimistic-concurrency.md` — Every Job and PO mutation requires an `If-Match` header carrying the latest ETag; the server rejects mismatches with `412` and missing headers with `428`, atomi…
- `docs/adr/0004-job-delta-envelope.md` — Clients submit `{change_id, fields, before, after, before_checksum, etag}` for every Job update; the backend re-canonicalises, verifies the checksum, persists a…
- `docs/adr/0005-emit-tools-pattern.md` — Each quote-chat mode terminates by calling an `emit_<mode>_result` tool whose parameter schema *is* the mode's output schema.
- `docs/adr/0006-rest-resource-hierarchy.md` — Identifiers live in the URL path (not body, not query); request bodies carry data only; one endpoint per operation — no conditional routing inside views.
- `docs/adr/0008-frontend-subtree-merge.md` — Pull the frontend repo into `frontend/` via `git subtree add` so backend + frontend share one history, one CI, one deploy script, and one PR for any cross-cutti…
- `docs/adr/0009-env-consolidation-app-domain.md` — Frontend build and test tooling reads `APP_DOMAIN` from the backend `.env` (resolved by convention at `../.env`) and derives URLs and allowed hosts from it.
- `docs/adr/0010-single-deploy-script.md` — One `scripts/deploy.sh` handles PROD, UAT, and SCHEDULER via hostname detection. CD runs it against both UAT machines in parallel with `continue-on-error`; the …
- `docs/adr/0011-codesight-precommit-wiki.md` — Commit `.codesight/` and `docs/.codesight/` to git. Regenerate both on pre-commit via `npx codesight --wiki` and `npx codesight --mode knowledge`.
- `docs/adr/0012-accounting-provider-strategy.md` — `AccountingProvider` is a Protocol; per-backend implementations (Xero today, MYOB next) are resolved at request time via `get_provider()`. Runtime polymorphism …
- `docs/adr/0013-error-message-clarity-over-info-hiding.md` — Internal-tool error responses include the underlying exception message verbatim. Continue to include the persisted `AppError.id` as `details.error_id` for cross…
- `docs/adr/0014-explicit-else-branches.md` — `if` statements in non-trivial control flow include an explicit `else` branch, even when the `else` body is a comment or a no-op.
- `docs/adr/0015-fix-data-not-fallback.md` — When a consumer finds data shaped differently from the model's contract, repair the data (migration, emission fix, or both). Never soften the consumer.
- `docs/adr/0016-ambiguous-names-trigger-rename.md` — When a name is found to carry more than one meaning, rearchitect and rename every occurrence in a dedicated PR. No baseline, no allowlist, no "we'll fix it when…
- `docs/adr/0017-zero-backwards-compatibility.md` — When a name, URL, signature, or shape changes, every caller changes in the same PR. No deprecation aliases, no dual-name field readers, no parallel old-and-new …
- `docs/adr/0018-fail-early-no-fallbacks.md` — Validate inputs at the entry point, check the bad branch first, and never coerce missing or malformed values to defaults that mask the underlying problem.
- `docs/adr/0019-mandatory-error-persistence.md` — Every `except` block calls `persist_app_error(exc)` before re-raising. Errors live in the database, not just in stdout.
- `docs/adr/0020-frontend-backend-separation.md` — Backend owns data integrity, calculations, persistence, and external integrations. Frontend owns presentation, UI state, and ergonomics. The boundary line is th…
- `docs/adr/0021-frontend-generated-api-client-only.md` — All frontend HTTP traffic goes through `/src/api/generated/api.ts`. Types come from the OpenAPI schema via `z.infer<typeof schemas.X>`. No raw `fetch`/`axios`, …
- _…and 2 more_

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
- `docs/adr/0007-xero-payroll-sync.md` — Split a week's `CostLine` time entries into work / other-leave / annual-or-sick / unpaid buckets and post each through the right Xero surface, with Draft-pay-ru…
- `frontend/manual/enquiries/new-customer-call.md` — **When to use:** A new or existing customer calls asking about work they need done.

### Session Logs (1)
- `frontend/manual/end-of-week/weekly-checklist.md` — **When to use:** End of the week admin procedures -- making sure nothing's fallen through the cracks.

### General Notes (87)
- `docs/plans/2026-05-01-timesheet-entry-business-rules.md` — 2026-05-01 — The E2E test `staff-wage-loading.spec.ts:97` is failing because nobody has documented what the columns on the timesheet entry screen actually *mean*. The test, …
- `docs/plans/2026-04-28-leave-entries-csv-input.md` — 2026-04-28 — **Trello:** https://trello.com/c/UsstYu5I
- `docs/plans/2026-04-28-utc-localdate-sweep.md` — 2026-04-28 — Eliminate a class of subtle "off by one day" bugs caused by calling `.date()` on
- `docs/plans/2026-04-16-sales-pipeline-report.md` — 2026-04-16 — Build a full `Sales Pipeline Report` that answers one primary question: is enough approved work flowing into the shop, and if not, where is the bottleneck? The …
- `CLAUDE.md` — This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. `AGENTS.md` is a symlink to this file so Codex, Cursor, a…
- `README.md` — A Django + Vue.js job/project management system for businesses that do lots of small-to-medium jobs for many clients. Originally built for [Morris Sheetmetal](h…
- `docs/README.md` ← 1 refs — DocketWorks is a job/project management system for businesses that do lots of relatively small jobs for many clients — fabrication shops, IT consultancies, trad…
- `docs/adr/README.md` — Short records that tell future developers how to code in this codebase: the problem, the decision, the why, the alternatives ruled out, and the consequences. Re…
- `docs/architecture.md` ← 1 refs — DocketWorks is a Django-based web application that digitizes paper-based workflows from quote generation to job completion and invoicing for businesses that do …
- `docs/client_onboarding.md` ← 2 refs — Everything needed to take a new client from signed contract to running instance. This is the handoff document for the onboarding specialist.
- `docs/development_session.md` ← 2 refs — Steps to start a development session. For first-time setup, see [initial_install.md](initial_install.md).
- `docs/initial_install.md` ← 5 refs — Dev machine setup. One-off steps that persist across restores.
- `docs/instance-setup-demo.md` ← 1 refs — Onboard a prospect for a paid trial of DocketWorks. Uses dummy staff but the prospect's real rates, markups, and configuration. Connects to Xero Demo Company.
- `docs/instance-setup-production.md` ← 1 refs — Set up a production instance for a client connecting to their real Xero organisation.
- `docs/msm-cutover.md` — Move MSM production from the old server (`/home/django_user`, MariaDB, `192.168.1.17`) to the new
- `docs/ngrok_setup.md` ← 1 refs — Set up ngrok tunnels for local development. Do this first — you'll need the domain for Xero app configuration.
- `docs/plans/as-long-as-teh-bubbly-volcano.md` — `CompanyDefaults` has two image fields:
- `docs/plans/now-the-performance-concerns-stateful-taco.md` — Two Copilot review comments on #162 flagged the Sales Pipeline service as having hot paths that do Python-side work which could move to SQL:
- `docs/plans/right-let-s-start-implementing-stateful-whisper.md` — Trello card [#276](https://trello.com/c/kEfIg8fA) covers two related JobEvent description bugs spotted in prod, plus a follow-up audit comment. The agreed shape…
- `docs/restore-prod-to-nonprod.md` ← 3 refs — Restore a production backup to any non-production environment (dev or server instance). This guide is environment-agnostic: assume venv active, `.env` loaded, i…
- _…and 67 more_

---
_Generated by [codesight](https://github.com/Houseofmvps/codesight) v1.10.0_