# docketworks — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**docketworks** is a mixed project built with django, using django for data persistence.

## Scale

92 API routes · 43 database models · 181 UI components · 10 middleware layers · 68 environment variables

## Subsystems

- **[Auth](./auth.md)** — 6 routes — touches: auth, payment, upload
- **[Payments](./payments.md)** — 1 routes — touches: auth, payment, upload
- **[Urls](./urls.md)** — 84 routes — touches: auth, payment, upload
- **[Infra](./infra.md)** — 1 routes

**Database:** django, 43 models — see [database.md](./database.md)

**UI:** 181 components (vue) — see [ui.md](./ui.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `frontend/src/api/generated/api.ts` — imported by **27** files
- `frontend/tests/fixtures/auth.ts` — imported by **27** files
- `frontend/tests/fixtures/helpers.ts` — imported by **19** files
- `frontend/src/utils/debug.ts` — imported by **14** files
- `/apps.py` — imported by **9** files
- `frontend/src/api/client.ts` — imported by **7** files

## Required Environment Variables

- `ACCOUNTING_BACKEND` — `docketworks/settings.py`
- `APP_URL` — `frontend/scripts/capture_metrics.cjs`
- `BASE_URL` — `frontend/src/router/index.ts`
- `CI` — `frontend/playwright.config.ts`
- `DJANGO_PASSWORD` — `frontend/scripts/capture_metrics.cjs`
- `DJANGO_RUN_SCHEDULER` — `docketworks/settings.py`
- `DJANGO_USER` — `frontend/scripts/capture_metrics.cjs`
- `DRY_RUN` — `scripts/copy_material_lines.py`
- `LOG_DIR` — `docketworks/settings.py`
- `MEDIA_ROOT` — `docketworks/settings.py`
- `PLAYWRIGHT_BROWSER_CHANNEL` — `frontend/tests/scripts/xero-login.ts`
- `REDIS_HOST` — `docketworks/settings.py`
- _...4 more_

---
_Back to [index.md](./index.md) · Generated 2026-04-22_