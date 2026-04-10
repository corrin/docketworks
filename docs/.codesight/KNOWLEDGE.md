# Knowledge Map — docketworks
> 167 notes · 0 decisions · 10 open questions · 2026-02-24 → 2026-04-10

> **AI Primer:** This knowledge base spans 2026-02-24 to 2026-04-10 (167 notes). Key topics: verification, tips, steps, what youll need. 10 open questions remain.

## Open Questions (10)
- 3.  **Database:** Is PostgreSQL running? Do credentials in `.env` match the `CREATE ROLE` command?
- 4.  **Migrations:** Run `python manage.py migrate`. Any errors?
- 5.  **ngrok:** Is the ngrok terminal running without errors? Does the domain match Xero's redirect URI and `.env`? Is the port correct?
- Option A: Sum of time entries for this job?
- Option B: Estimated hours from quote/cost set?
- Option C: New field on Job model?
- 1. **Workshop time allocated** - What is the data source?
- Estimated hours from quote?
- 2. **PO-0334 orphans:** These have costs on Jobs 96257 and 95427. Are the valid CostLines the correct ones, or are the orphans the real deliveries?
- *Aggregate mode:** Do the totals match?

## Recurring Themes
verification · tips · steps · what youll need · what happens next · files to modify · implementation steps · troubleshooting · problem statement · benefits · implementation notes · error handling

## People
@docketworks · @transaction · @pytest · @patch · @morrissheetmetal · @playwright · @tailwindcss · @vitejs · @cmeconnect · @require_superuser · @can_manage_timesheets · @vulcansteel · @coregas · @xtra · @vodafone · @fluidandgeneral · @ppsindustries · @eclgroup · @medifab · @akenz

## Hub Notes (most referenced)
- `docs/initial_install.md` — **5** incoming references — Initial Installation Guide
- `docs/client_onboarding.md` — **2** incoming references — Client Onboarding
- `docs/development_session.md` — **2** incoming references — Development Session Startup
- `docs/restore-prod-to-nonprod.md` — **2** incoming references — Restore Production to Non-Production
- `docs/server_setup.md` — **2** incoming references — Server Setup

## Note Index (167)

### Specs & PRDs (29)
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
- `docs/plans/jsa-swp-api.md` — This document describes the backend API for AI-powered Job Safety Analysis (JSA) and Safe Work Procedure (SWP) generation and editing.
- _…and 9 more_

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

### General Notes (132)
- `docs/plans/2026-04-10-codesight-setup.md` — 2026-04-10 — Codesight is already installed (`npx codesight` works, v1.10.0) and has been run manually — there are three untracked `.codesight/` directories (root, `frontend…
- `docs/plans/2026-04-09-wip-report-script.md` — 2026-04-09 — A WIP (Work In Progress) report was prototyped directly in production as a CLI script. The business logic works — it calculates uninvoiced value on active jobs …
- `docs/plans/completed/2026-04-02-fix-po-e2e-autosave.md` — 2026-04-02 — E2E test `add a line item to the purchase order` times out waiting for a PATCH. Two issues:
- `docs/plans/completed/2026-04-02-rename-tables-to-defaults.md` — 2026-04-02 — Moving from MySQL to PostgreSQL. Since no production Postgres data exists yet, this is the clean window to rename 30 tables from their legacy `workflow_*` names…
- `docs/plans/completed/2026-04-02-timesheet-superuser-gate-plan.md` — 2026-04-02 — **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan tas…
- `docs/plans/completed/2026-04-02-timesheet-superuser-gate.md` — 2026-04-02 — Timesheet views expose sensitive pay data (how much staff are paid, hours worked at what rates). Currently all 10 timesheet API views independently set `permiss…
- `docs/plans/completed/2026-04-02-workshop-timesheet-test-plan.md` — 2026-04-02 — The workshop timesheet API (`/api/job/workshop/timesheets/`) has zero backend test coverage. Need to verify that normal (non-admin) staff users can create times…
- `docs/plans/2026-03-31-scheduler-service-per-instance.md` — 2026-03-31 — Each docketworks instance needs a running APScheduler process for Xero sync, auto-archiving, scraper jobs, etc. Currently there is no systemd service for the sc…
- `docs/plans/2026-03-31-scheduler-service-plan.md` — 2026-03-31 — **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan tas…
- `docs/plans/completed/2026-03-31-e2e-test8-edit-fix.md` — 2026-03-31 — Test 8 in `create-estimate-entry.spec.ts` fails because `dblclick()` + `keyboard.type()` on `<input type="number">` doesn't reliably select/replace text in head…
- `docs/plans/completed/2026-03-31-env-consolidation.md` — 2026-03-31 — **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan tas…
- `docs/plans/2026-03-29-finalize-restore-doc.md` — 2026-03-29 — The restore process is the same on dev and UAT. The restore doc should be environment-agnostic: assume venv active, .env loaded, in the project root (which is `…
- `docs/plans/2026-03-28-debranding-and-stale-docs.md` — 2026-03-28 — **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan tas…
- `frontend/docs/plans/2026-03-05-backend-requirements-process-documents.md` — 2026-03-05 — **Context:** The frontend needs these API changes to build the Process Documents UI. The ProcessDocument and ProcessDocumentEntry models already exist. Some end…
- `frontend/docs/plans/2026-03-05-process-documents-implementation.md` — 2026-03-05 — **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
- `docs/plans/2026-03-03-process-documents-plan.md` — 2026-03-03 — **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
- `frontend/docs/plans/2026-02-24-payroll-reconciliation-design.md` — 2026-02-24 — **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
- `AGENTS.md` — Authoritative guidance for AI coding agents working in the DocketWorks backend. Rules are distilled from `CLAUDE.md`, `.kilocode/rules/*.md`, and project readme…
- `CLAUDE.md` — This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
- `README.md` — A Django + Vue.js job/project management system for businesses that do lots of small-to-medium jobs for many clients. Originally built for [Morris Sheetmetal](h…
- _…and 112 more_

---
_Generated by [codesight](https://github.com/Houseofmvps/codesight) v1.10.0_