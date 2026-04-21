# Move `weekend_timesheets_enabled` to `CompanyDefaults`

## Context

Weekend-mode timesheets are currently gated by two separate flags:

- `VITE_WEEKEND_TIMESHEETS_ENABLED` in `frontend/.env` — baked in at Vite build time.
- `WEEKEND_TIMESHEETS_ENABLED` in the backend `.env` — read via `os.getenv` in two places.

They have already drifted (dev backend `.env:61` says `False`, server template `env-instance.template:56` says `True`) and neither can be toggled without a redeploy or restart. Operators can't self-serve.

We sell docketworks to multiple single-tenant installs, and different clients want different behaviour (MSM: 5-day; others may want 7-day). Moving this to `CompanyDefaults` matches the existing pattern for per-install configuration (`time_markup`, `xero_payroll_calendar_name`, `financial_year_start_month`, Mon–Fri working hours, etc.) and lets an admin flip it from the existing company-defaults form.

Outcome: one source of truth in the DB, togglable in the admin UI, no rebuild or restart required.

## Approach

1. **Backend model** — add `weekend_timesheets_enabled = BooleanField(default=False)` to `CompanyDefaults`. Create a migration (pure schema, no data backfill).
2. **Backend reads** — replace both `os.getenv("WEEKEND_TIMESHEETS_ENABLED", ...)` call sites with `CompanyDefaults.get_solo().weekend_timesheets_enabled`.
3. **API exposure** — `CompanyDefaults` is already serialized and returned via `company_defaults_retrieve`; adding the field to the model flows through automatically. Regenerate the OpenAPI schema.
4. **Frontend reads** — replace `FeatureFlagsService.isWeekendTimesheetsEnabled()` and the raw `import.meta.env.VITE_WEEKEND_TIMESHEETS_ENABLED` check with a read from the company-defaults store. Delete `feature-flags.service.ts` (this is its only flag).
5. **Admin UI** — add the toggle to `CompanyDefaultsFormModal.vue` / `AdminCompanyView.vue`.
6. **Cleanup** — remove both env vars from all `.env`, `.env.example`, and server-template files; remove `readonly VITE_WEEKEND_TIMESHEETS_ENABLED` from `frontend/env.d.ts`.

No data migration needed — the default (`False`) preserves existing MSM behaviour.

## Changes

### Backend

- `apps/workflow/models/company_defaults.py` — add `weekend_timesheets_enabled` field (Boolean, default `False`, `help_text`).
- `apps/workflow/migrations/XXXX_companydefaults_weekend_timesheets.py` — new migration.
- `apps/timesheet/views/api.py:293-295` — delete `_is_weekend_enabled()` method; replace `self._is_weekend_enabled()` at line 264 with `CompanyDefaults.get_solo().weekend_timesheets_enabled`. The `weekend_enabled`/`week_type` response fields stay (informational; frontend ignores them but they're in the schema).
- `apps/timesheet/services/daily_timesheet_service.py:87`, `:186`, `:348` — replace `cls._is_weekend_enabled()` with `CompanyDefaults.get_solo().weekend_timesheets_enabled`; delete the `_is_weekend_enabled` classmethod.
- `.env.example:64` — remove `WEEKEND_TIMESHEETS_ENABLED=False`.
- `.env:61` (dev) — remove the line.
- `scripts/server/templates/env-instance.template:56` — remove.

### Frontend

- `frontend/src/stores/companyDefaults.ts` — no change needed if it already exposes the raw CompanyDefaults object; verify the new field surfaces through Zod inference after `npm run update-schema && npm run gen:api`.
- `frontend/src/stores/timesheet.ts:43,254` — initialise `weekendEnabled` from the company-defaults store instead of `FeatureFlagsService`. Ensure `loadCompanyDefaults()` has completed before `initializeFeatureFlags` reads it (or merge the two: read the value lazily in `displayDays` and drop `initializeFeatureFlags` entirely).
- `frontend/src/views/WeeklyTimesheetView.vue:459-462` — replace `import.meta.env.VITE_WEEKEND_TIMESHEETS_ENABLED === 'true'` with a read from the company-defaults store.
- `frontend/src/views/TimesheetEntryView.vue:1181,1200,1210,1223` — uses `timesheetStore.weekendEnabled`; no change needed once the store reads from CompanyDefaults.
- `frontend/src/services/feature-flags.service.ts` — **delete** (only exposed this one flag).
- `frontend/env.d.ts:28` — remove `VITE_WEEKEND_TIMESHEETS_ENABLED`.
- `frontend/.env.example:5` — remove.
- `frontend/.env:12` — remove.
- `scripts/server/templates/frontend-env-instance.template:8` — remove.
- `frontend/src/components/CompanyDefaultsFormModal.vue` — add a labelled checkbox for `weekend_timesheets_enabled` ("Show weekends in timesheets").
- `frontend/src/views/AdminCompanyView.vue` — wire the new field into the form if it's enumerated explicitly there.

### Ops

- No data migration. Default is `False`, matching current dev/MSM.
- For UAT/prod installs that want 7-day mode (per `env-instance.template` default of `True`), an admin flips the toggle post-deploy.

## Critical Files

- `apps/workflow/models/company_defaults.py`
- `apps/timesheet/views/api.py` — line 264, 293–295
- `apps/timesheet/services/daily_timesheet_service.py` — lines 87, 186, 348
- `frontend/src/stores/timesheet.ts` — lines 43, 252–278
- `frontend/src/views/WeeklyTimesheetView.vue` — lines 459–481, 614–628
- `frontend/src/services/feature-flags.service.ts` — delete
- `frontend/src/components/CompanyDefaultsFormModal.vue`

## Existing utilities to reuse

- `CompanyDefaults.get_solo()` — already used throughout the backend (`weekly_timesheet_service.py:93`, etc.) — canonical read pattern.
- `company_defaults_retrieve` API + `companyDefaults` store on the frontend — already loaded by timesheet views via `loadCompanyDefaults()` in `stores/timesheet.ts:280`.
- `admin-company-defaults-service.ts` + `AdminCompanyView.vue` — existing admin edit surface.

## Verification

1. `python manage.py migrate` — migration applies cleanly.
2. Backend unit check: `CompanyDefaults.get_solo().weekend_timesheets_enabled` returns `False` on a fresh DB.
3. `npm run update-schema && npm run gen:api` — new field appears in generated types.
4. `npm run type-check` in `frontend/` — passes after removals.
5. Manual: with flag off, `/weekly-timesheet` renders 5 columns Mon–Fri; daily-navigation arrows skip weekends. With flag on (toggled via admin form), same views show 7 columns and navigate into Sat/Sun.
6. `rg -n "WEEKEND_TIMESHEETS_ENABLED"` returns nothing (both env vars fully removed).
7. E2E: run the timesheet playwright specs with the flag off (default) and again after toggling it on in the admin UI — both paths pass.
