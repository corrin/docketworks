# frontend-jobs-manager — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**frontend-jobs-manager** is a typescript project built with raw-http.

## Scale

61 database models · 181 UI components · 3 middleware layers · 15 environment variables

**Database:** unknown, 61 models — see [database.md](./database.md)

**UI:** 181 components (vue) — see [ui.md](./ui.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `src/api/generated/api.ts` — imported by **75** files
- `src/utils/debug.ts` — imported by **51** files
- `src/api/client.ts` — imported by **46** files
- `tests/fixtures/auth.ts` — imported by **27** files
- `tests/fixtures/helpers.ts` — imported by **19** files
- `src/utils/string-formatting.ts` — imported by **14** files

## Required Environment Variables

- `APP_URL` — `scripts/capture_metrics.cjs`
- `BASE_URL` — `src/router/index.ts`
- `CI` — `playwright.config.ts`
- `DEBUG` — `tests/fixtures/auth.ts`
- `DJANGO_PASSWORD` — `scripts/capture_metrics.cjs`
- `DJANGO_USER` — `scripts/capture_metrics.cjs`
- `MODE` — `src/utils/debug.ts`
- `PLAYWRIGHT_BROWSER_CHANNEL` — `tests/scripts/xero-login.ts`

---
_Back to [index.md](./index.md) · Generated 2026-04-16_