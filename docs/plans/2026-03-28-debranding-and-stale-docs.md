# De-brand MSM / Clean Up Stale Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substantially reduce hardcoded Morris Sheetmetal / MSM references from product code and docs, update stale `jobs_manager` references, and clean up monorepo transition artifacts — making DocketWorks properly multi-tenant while keeping MSM as the showcase client.

**Architecture:** Text-only changes across docs, config, skills, and one management command. No schema changes. No migrations. The `CompanyDefaults` model already has `shop_client_name` — we just need code to use it instead of hardcoding `"MSM (Shop)"`.

**Tech Stack:** Django 6, Python, Markdown, JavaScript

---

### Task 1: Update `CLAUDE.md` — multi-tenant product description

**Files:**
- Modify: `CLAUDE.md:19`

- [ ] **Step 1: Edit CLAUDE.md core purpose description**

Replace line 19:

```
Django-based job/project management system for custom metal fabrication business (Morris Sheetmetal). Digitizes a 50+ year paper-based workflow from quote generation to job completion and invoicing.
```

with:

```
Multi-tenant Django-based job/project management system for custom manufacturing businesses. Originally built for Morris Sheetmetal, now sold to multiple clients. Each instance has its own CompanyDefaults, branding, and integrations. Digitizes paper-based workflows from quote generation to job completion and invoicing.
```

- [ ] **Step 2: Verify the subagent guidance is still present**

The existing text at line 9 about spawning a subagent for frontend work should be kept — the frontend uses completely different tooling (Vue/TS/npm vs Django/Python/poetry) so the subagent pattern is still valuable. No change needed here.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for multi-tenant product"
```

---

### Task 2: Update `AGENTS.md` — multi-tenant, fix monorepo reference

**Files:**
- Modify: `AGENTS.md:7-8`

- [ ] **Step 1: Edit AGENTS.md mission context**

Replace lines 7-8:

```markdown
- Morris Sheetmetal relies on this Django 5.x + DRF system to digitize quote -> production -> invoicing workflows. Business expectations live in `docs/README.md`.
- Backend agents own persistence, business logic, integrations, and REST APIs. Frontend/UI responsibilities live in the separate Vue + Django-templates project.
```

with:

```markdown
- DocketWorks is a multi-tenant Django 6 + DRF system that digitizes quote -> production -> invoicing workflows for custom manufacturing businesses. Morris Sheetmetal is the showcase client. Business expectations live in `docs/README.md`.
- Backend agents own persistence, business logic, integrations, and REST APIs. The Vue frontend lives in `frontend/` within this monorepo.
```

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md for multi-tenant product and monorepo"
```

---

### Task 3: Update `README.md` (root) — fix DB requirement

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Edit README.md**

Replace the Requirements section line:

```
- **MariaDB 11.5.2** (locally)
```

with:

```
- **PostgreSQL 16+**
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README DB requirement to PostgreSQL"
```

---

### Task 4: Update `docs/README.md` — multi-tenant product docs

**Files:**
- Modify: `docs/README.md:1-5`

- [ ] **Step 1: Edit docs/README.md header and overview**

Replace lines 1-5:

```markdown
# Project Documentation: Morris Sheetmetal Works Workflow Management System

## **Project Overview**

Morris Sheetmetal Works is a small jobbing shop specializing in custom metal fabrication for a variety of customer needs, ranging from fencepost covers to manhole covers. The goal of this project is to transition the company from a paper-based workflow to a fully digital system, improving efficiency and enabling better oversight while maintaining or increasing operational speed.
```

with:

```markdown
# DocketWorks — Project Documentation

## **Project Overview**

DocketWorks is a job/project management system for custom manufacturing businesses (fabrication shops, machine shops, etc.). Originally built for Morris Sheetmetal — a small jobbing shop specializing in custom metal fabrication — it now serves multiple clients. The system transitions paper-based workflows to a fully digital system, improving efficiency and enabling better oversight while maintaining or increasing operational speed.
```

- [ ] **Step 2: Commit**

```bash
git add docs/README.md
git commit -m "docs: update docs/README.md for multi-tenant product"
```

---

### Task 5: Update `docs/architecture.md` — generic description, fix DB reference

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Edit architecture.md system overview**

Replace line 5:

```markdown
Morris Sheetmetal Works Job Management System is a Django-based web application that digitizes a 50+ year paper-based workflow from quote generation to job completion and invoicing for a custom metal fabrication business.
```

with:

```markdown
DocketWorks is a multi-tenant Django-based web application that digitizes paper-based workflows from quote generation to job completion and invoicing for custom manufacturing businesses. Originally built for Morris Sheetmetal.
```

- [ ] **Step 2: Update the database in the mermaid diagram**

In the mermaid diagram around line 28, change:

```
        MariaDB[(MariaDB)]
```

to:

```
        PostgreSQL[(PostgreSQL)]
```

Also update the arrow label around line 36:

```
    Core --> MariaDB
```

to:

```
    Core --> PostgreSQL
```

- [ ] **Step 3: Update deployment section**

Around line 295, change:

```markdown
- **Database**: MariaDB with appropriate sizing
```

to:

```markdown
- **Database**: PostgreSQL 16+
```

- [ ] **Step 4: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: update architecture.md for multi-tenant, fix DB to PostgreSQL"
```

---

### Task 6: Update `frontend/README.md` — fix monorepo reference, remove MSM ngrok domain

**Files:**
- Modify: `frontend/README.md:4,22`

- [ ] **Step 1: Edit frontend/README.md**

Replace line 4:

```markdown
It communicates with the [DocketWorks backend](https://github.com/corrin/docketworks).
```

with:

```markdown
It communicates with the Django backend in the repository root.
```

Replace the ngrok example on line 22:

```
ngrok http 5173 --domain=docketworks-msm-dev.ngrok-free.app
```

with:

```
ngrok http 5173 --domain=<your-ngrok-domain>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/README.md
git commit -m "docs: fix frontend README for monorepo, remove MSM-specific ngrok domain"
```

---

### Task 7: Fix `create_special_job.py` — use CompanyDefaults instead of hardcoded `"MSM (Shop)"`

**Files:**
- Modify: `apps/timesheet/management/commands/create_special_job.py:47-51`

- [ ] **Step 1: Edit create_special_job.py**

Replace the hardcoded client lookup (lines 47-51):

```python
        # Resolve client (MSM (Shop) — same as other special jobs)
        try:
            client = Client.objects.get(name="MSM (Shop)")
        except Client.DoesNotExist:
            raise CommandError("Client 'MSM (Shop)' not found")
```

with:

```python
        # Resolve shop client from CompanyDefaults
        from apps.workflow.models import CompanyDefaults

        defaults = CompanyDefaults.objects.first()
        if not defaults or not defaults.shop_client_name:
            raise CommandError(
                "CompanyDefaults.shop_client_name is not configured. "
                "Set it in the admin before creating special jobs."
            )
        try:
            client = Client.objects.get(name=defaults.shop_client_name)
        except Client.DoesNotExist:
            raise CommandError(
                f"Client '{defaults.shop_client_name}' not found. "
                "Check CompanyDefaults.shop_client_name matches an existing client."
            )
```

- [ ] **Step 2: Commit**

```bash
git add apps/timesheet/management/commands/create_special_job.py
git commit -m "fix: use CompanyDefaults.shop_client_name instead of hardcoded MSM (Shop)"
```

---

### Task 8: Fix `scripts/dump_settings.py` — wrong Django settings module

**Files:**
- Modify: `scripts/dump_settings.py:19`

- [ ] **Step 1: Edit dump_settings.py**

Replace line 19:

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jobs_manager.settings")
```

with:

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
```

- [ ] **Step 2: Commit**

```bash
git add scripts/dump_settings.py
git commit -m "fix: correct Django settings module in dump_settings.py"
```

---

### Task 9: Fix `frontend/scripts/capture_metrics.cjs` — hardcoded MSM URLs

**Files:**
- Modify: `frontend/scripts/capture_metrics.cjs:27-28`

- [ ] **Step 1: Edit capture_metrics.cjs**

Replace the hardcoded URLs:

```javascript
    production: 'https://office.morrissheetmetal.co.nz',
    uat: 'https://uat-office.morrissheetmetal.co.nz',
```

with environment-variable-driven URLs:

```javascript
    production: process.env.PRODUCTION_URL || (() => { throw new Error('PRODUCTION_URL env var required') })(),
    uat: process.env.UAT_URL || (() => { throw new Error('UAT_URL env var required') })(),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/scripts/capture_metrics.cjs
git commit -m "fix: replace hardcoded MSM URLs with env vars in capture_metrics"
```

---

### Task 10: Update `.claude/skills/add-stock/SKILL.md` — remove hardcoded URL

**Files:**
- Modify: `.claude/skills/add-stock/SKILL.md:21`

- [ ] **Step 1: Edit SKILL.md**

Replace line 21:

```markdown
- A full URL like `https://office.morrissheetmetal.co.nz/jobs/<uuid>?tab=actual` — extract the UUID
```

with:

```markdown
- A full URL like `https://<instance>.docketworks.site/jobs/<uuid>?tab=actual` — extract the UUID
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/add-stock/SKILL.md
git commit -m "docs: use generic URL in add-stock skill"
```

---

### Task 11: Update `docs/plans/2026-03-03-process-documents-plan.md` — fix stale tech stack

**Files:**
- Modify: `docs/plans/2026-03-03-process-documents-plan.md:9`

- [ ] **Step 1: Edit the tech stack line**

Replace:

```markdown
**Tech Stack:** Django 5.2, DRF, Google Docs/Drive API, MariaDB, Vue 3 frontend (separate repo)
```

with:

```markdown
**Tech Stack:** Django 6, DRF, Google Docs/Drive API, PostgreSQL, Vue 3 frontend (in `frontend/`)
```

- [ ] **Step 2: Commit**

```bash
git add docs/plans/2026-03-03-process-documents-plan.md
git commit -m "docs: fix stale tech stack in process documents plan"
```

---

### Task 12: Delete stale root-level `workshop_pdf_service.py`

**Files:**
- Delete: `workshop_pdf_service.py` (root level)

The real file is at `apps/job/services/workshop_pdf_service.py`. The root copy is 1130 lines, nearly identical, and references stale `jobs_manager/logo_msm.png` paths. It's not imported anywhere.

- [ ] **Step 1: Verify the root file is not imported**

Run: `grep -r "from workshop_pdf_service\|import workshop_pdf_service" --include="*.py" .`
Expected: No matches (or only the file itself).

- [ ] **Step 2: Delete the stale file**

```bash
git rm workshop_pdf_service.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove stale root-level workshop_pdf_service.py"
```

---

### Task 13: Delete stale root-level `company_defaults_backup_20260209.py`

**Files:**
- Delete: `company_defaults_backup_20260209.py` (root level)

This is a one-off backup script with hardcoded MSM data. It shouldn't be in the repo.

- [ ] **Step 1: Delete the stale file**

```bash
git rm company_defaults_backup_20260209.py
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove stale company_defaults_backup script"
```

---

## Files NOT changed (and why)

### Completed plan docs (`docs/plans/completed/`)
Historical records — `gemini_chat_implementation.md`, `deployment_consolidation.md`, `monorepo-migration.md`, `dryrun_mysql_to_postgres.md`, `BACKEND_CHANGES_COSTLINE_ESTIMATE.md` all reference `jobs_manager` but these are accurate historical snapshots. Changing them would falsify the record.

### `docs/production-cutover-plan.md`
Active migration doc that references `jobs_manager` as the actual MariaDB database name being migrated from. These references are factually correct for the migration process.

### Example-style MSM references
Files like `docs/initial_install.md`, `docs/client_onboarding.md`, `docs/uat_setup.md`, `.env.example`, and UAT scripts use `msm` as an *example* client code in a multi-tenant context (e.g., `dw_msm_dev`). This is the correct pattern — they're showing how to set up *any* client instance.

### `docs/development_session.md`
Uses `docketworks-msm-dev.ngrok-free.app` as the developer's actual ngrok domain. This is specific to one developer's setup and is documented as such. Fine as-is.

### Model help_text (`company_defaults.py`)
Uses MSM as an example in `help_text` strings (e.g., `"e.g., 'MSM' for Morris Sheetmetal"`). This is appropriate — help_text should show concrete examples.

### `apps/process/management/commands/import_dropbox_hs_documents.py`
Contains `"zMSM Old Docs"` in a skip-folders list and `office@morrissheetmetal.co.nz`. This is an MSM-specific data import command that would need to be parameterized for multi-tenant use, but that's a larger refactor beyond scope here.

### `apps/process/tests/test_procedure_service.py`
Uses `company_name="Morris Sheetmetal"` as test fixture data. Test data is fine — it's just a string value.

### `.env.precommit`
Uses `dw_msm_test` — this is a local CI config, not product code.
