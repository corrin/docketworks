# Dependency Graph

## Most Imported Files (change these carefully)

- `frontend/tests/fixtures/auth.ts` — imported by **28** files
- `frontend/src/api/generated/api.ts` — imported by **27** files
- `frontend/tests/fixtures/helpers.ts` — imported by **20** files
- `frontend/src/utils/debug.ts` — imported by **14** files
- `/apps.py` — imported by **9** files
- `frontend/src/api/client.ts` — imported by **7** files
- `frontend/src/utils/dateUtils.ts` — imported by **6** files
- `/enums.py` — imported by **5** files
- `frontend/tests/scripts/db-backup-utils.ts` — imported by **5** files
- `frontend/src/stores/jobs.ts` — imported by **5** files
- `/utils.py` — imported by **3** files
- `/models.py` — imported by **3** files
- `/xero_helpers.py` — imported by **3** files
- `/xero_base_manager.py` — imported by **3** files
- `frontend/src/services/costline.service.ts` — imported by **3** files
- `frontend/src/stores/auth.ts` — imported by **3** files
- `frontend/src/services/job.service.ts` — imported by **3** files
- `frontend/src/constants/advanced-filters.ts` — imported by **3** files
- `/costing.py` — imported by **2** files
- `/job.py` — imported by **2** files

## Import Map (who imports what)

- `frontend/tests/fixtures/auth.ts` ← `frontend/tests/company-defaults.spec.ts`, `frontend/tests/example.spec.ts`, `frontend/tests/job/create-estimate-entry.spec.ts`, `frontend/tests/job/create-job-with-new-client.spec.ts`, `frontend/tests/job/create-job.spec.ts` +23 more
- `frontend/src/api/generated/api.ts` ← `frontend/src/api/client.ts`, `frontend/src/composables/useAddEmptyCostLine.ts`, `frontend/src/composables/useAddMaterialCostLine.ts`, `frontend/src/composables/useAppLayout.ts`, `frontend/src/composables/useCostLineAutosave.ts` +22 more
- `frontend/tests/fixtures/helpers.ts` ← `frontend/tests/fixtures/auth.ts`, `frontend/tests/job/create-estimate-entry.spec.ts`, `frontend/tests/job/create-job-with-new-client.spec.ts`, `frontend/tests/job/job-attachments.spec.ts`, `frontend/tests/job/job-header.spec.ts` +15 more
- `frontend/src/utils/debug.ts` ← `frontend/src/api/client.ts`, `frontend/src/composables/useAppLayout.ts`, `frontend/src/composables/useCreateCostLineFromEmpty.ts`, `frontend/src/composables/useJobAutosave.ts`, `frontend/src/composables/useOptimizedDragAndDrop.ts` +9 more
- `/apps.py` ← `apps/accounting/__init__.py`, `apps/accounts/__init__.py`, `apps/client/__init__.py`, `apps/job/__init__.py`, `apps/process/__init__.py` +4 more
- `frontend/src/api/client.ts` ← `frontend/src/composables/useJobEvents.ts`, `frontend/src/composables/useJobFinancials.ts`, `frontend/src/services/clientService.ts`, `frontend/src/services/daily-timesheet.service.ts`, `frontend/src/services/job.service.ts` +2 more
- `frontend/src/utils/dateUtils.ts` ← `frontend/src/composables/useAddMaterialCostLine.ts`, `frontend/src/composables/useCreateCostLineFromEmpty.ts`, `frontend/src/services/timesheet.service.ts`, `frontend/tests/staff/staff-wage-loading.spec.ts`, `frontend/tests/timesheet/create-timesheet-entry.spec.ts` +1 more
- `/enums.py` ← `apps/accounting/__init__.py`, `apps/job/__init__.py`, `apps/timesheet/__init__.py`, `apps/workflow/__init__.py`, `apps/workflow/api/__init__.py`
- `frontend/tests/scripts/db-backup-utils.ts` ← `frontend/playwright.config.ts`, `frontend/scripts/capture-screenshots.ts`, `frontend/tests/scripts/e2e-reset.ts`, `frontend/tests/scripts/global-teardown.ts`, `frontend/tests/scripts/xero-login.ts`
- `frontend/src/stores/jobs.ts` ← `frontend/src/composables/useCreateCostLineFromEmpty.ts`, `frontend/src/composables/useJobHeaderAutosave.ts`, `frontend/src/composables/useOptimizedKanban.ts`, `frontend/src/composables/useTimesheetEntryCalculations.ts`, `frontend/src/main.ts`
