# Dependency Graph

## Most Imported Files (change these carefully)

- `src/api/generated/api.ts` — imported by **73** files
- `src/api/client.ts` — imported by **52** files
- `src/utils/debug.ts` — imported by **50** files
- `tests/fixtures/auth.ts` — imported by **29** files
- `tests/fixtures/helpers.ts` — imported by **21** files
- `src/utils/dateUtils.ts` — imported by **15** files
- `src/utils/string-formatting.ts` — imported by **11** files
- `src/stores/auth.ts` — imported by **7** files
- `tests/scripts/db-backup-utils.ts` — imported by **5** files
- `src/stores/jobs.ts` — imported by **5** files
- `src/services/job.service.ts` — imported by **5** files
- `src/plugins/axios.ts` — imported by **5** files
- `src/services/costline.service.ts` — imported by **4** files
- `src/stores/companyDefaults.ts` — imported by **4** files
- `src/composables/useJobETags.ts` — imported by **3** files
- `src/composables/useJobDelta.ts` — imported by **3** files
- `src/constants/advanced-filters.ts` — imported by **3** files
- `src/router/index.ts` — imported by **3** files
- `src/composables/useConcurrencyEvents.ts` — imported by **2** files
- `src/composables/usePoConcurrencyEvents.ts` — imported by **2** files

## Import Map (who imports what)

- `src/api/generated/api.ts` ← `src/api/client.ts`, `src/composables/useActiveJob.ts`, `src/composables/useAddEmptyCostLine.ts`, `src/composables/useAddMaterialCostLine.ts`, `src/composables/useAppLayout.ts` +68 more
- `src/api/client.ts` ← `src/composables/useClientLookup.ts`, `src/composables/useContactManagement.ts`, `src/composables/useDataFreshness.ts`, `src/composables/useErrorApi.ts`, `src/composables/useJobEvents.ts` +47 more
- `src/utils/debug.ts` ← `src/api/client.ts`, `src/composables/useAppLayout.ts`, `src/composables/useCamera.ts`, `src/composables/useClientLookup.ts`, `src/composables/useContactManagement.ts` +45 more
- `tests/fixtures/auth.ts` ← `tests/company-defaults.spec.ts`, `tests/example.spec.ts`, `tests/job/create-estimate-entry.spec.ts`, `tests/job/create-job-with-new-client.spec.ts`, `tests/job/create-job.spec.ts` +24 more
- `tests/fixtures/helpers.ts` ← `tests/fixtures/auth.ts`, `tests/job/create-estimate-entry.spec.ts`, `tests/job/create-job-with-new-client.spec.ts`, `tests/job/job-attachments.spec.ts`, `tests/job/job-header.spec.ts` +16 more
- `src/utils/dateUtils.ts` ← `src/composables/useAddMaterialCostLine.ts`, `src/composables/useCreateCostLineFromEmpty.ts`, `src/composables/useFinancialYear.ts`, `src/composables/useStaffApi.ts`, `src/composables/useWorkshopTimesheetDay.ts` +10 more
- `src/utils/string-formatting.ts` ← `src/composables/useWorkshopCalendarSync.ts`, `src/composables/useWorkshopJob.ts`, `src/composables/useWorkshopTimesheetTimeUtils.ts`, `src/services/daily-timesheet.service.ts`, `src/services/job-aging-report.service.ts` +6 more
- `src/stores/auth.ts` ← `src/composables/useAppLayout.ts`, `src/composables/useDashboard.ts`, `src/composables/useJobHeaderAutosave.ts`, `src/composables/useLogin.ts`, `src/plugins/axios.ts` +2 more
- `tests/scripts/db-backup-utils.ts` ← `playwright.config.ts`, `scripts/capture-screenshots.ts`, `tests/scripts/e2e-reset.ts`, `tests/scripts/global-teardown.ts`, `tests/scripts/xero-login.ts`
- `src/stores/jobs.ts` ← `src/composables/useCreateCostLineFromEmpty.ts`, `src/composables/useJobFiles.ts`, `src/composables/useJobHeaderAutosave.ts`, `src/composables/useOptimizedKanban.ts`, `src/main.ts`
