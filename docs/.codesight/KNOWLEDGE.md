# Knowledge Map — docketworks
> 201 notes · 2 decisions · 10 open questions · 2026-02-24 → 2026-04-19

> **AI Primer:** This knowledge base spans 2026-02-24 to 2026-04-19 (201 notes). Key topics: verification, files to modify, tips, steps. Most recent decision: What we chose, stated as an imperative. One paragraph. 10 open questions remain.

## Key Decisions (2)
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
verification · files to modify · tips · steps · what youll need · what happens next · troubleshooting · fix · changes · design · purpose · implementation steps

## People
@docketworks · @morrissheetmetal · @msm · @transaction · @pytest · @patch · @extend_schema · @classmethod · @rowClick · @resolve · @unresolve · @update · @close · @playwright · @tailwindcss · @vitejs · @cmeconnect · @require_superuser · @can_manage_timesheets · @property

## Hub Notes (most referenced)
- `docs/initial_install.md` — **5** incoming references — Initial Installation Guide
- `docs/client_onboarding.md` — **2** incoming references — Client Onboarding
- `docs/development_session.md` — **2** incoming references — Development Session Startup
- `docs/restore-prod-to-nonprod.md` — **2** incoming references — Restore Production to Non-Production
- `docs/server_setup.md` — **2** incoming references — Server Setup
- `restore/extracted/usr/local/nvm/GOVERNANCE.md` — **2** incoming references — `nvm` Project Governance

## Note Index (201)

### Decision Records (1)
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

### Meeting Notes (3)
- `docs/plans/completed/2026-04-01-postgres-sequence-sync.md` — 2026-04-01 — E2E tests fail with `IntegrityError` on `workflow_historicaljob_pkey` because the custom `syncSequences` SQL query misses identity column sequences (all SimpleH…
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