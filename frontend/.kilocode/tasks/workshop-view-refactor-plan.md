# Workshop Views Refactor Plan

## Goals

- Improve readability and maintainability in `WorkshopJobView` and `WorkshopMyTimeView`.
- Isolate data-fetching, state, and formatting logic into composables.
- Split large templates into focused, testable components without altering behavior.

## Scope

- `src/views/WorkshopJobView.vue`
- `src/views/WorkshopMyTimeView.vue`
- New composables in `src/composables`
- New UI components under `src/components/workshop` (or relevant subfolders)

## Constraints

- Preserve current UI and behavior.
- Use existing API schemas from `@/api/generated/api`.
- Keep Tailwind and shadcn-vue patterns consistent with the rest of the app.

## Phase 1: WorkshopJobView Extraction

1. Create composable `useWorkshopJob`:
   - Responsibilities: load job, derived fields (speed quality, workshop time display), notes sanitization, date formatting.
2. Create composable `useWorkshopJobAttachments`:
   - Responsibilities: list attachments, toggle expand, preview fetch, download, cleanup.
3. Split template into components:
   - `WorkshopJobHeader`
   - `WorkshopJobKeyInfoCard`
   - `WorkshopJobSummaryCard`
   - `WorkshopJobDescriptionCard`
   - `WorkshopJobNotesCard`
   - `WorkshopJobAttachmentsCard`
4. Replace in-view logic with composable outputs and pass props to components.

## Phase 2: WorkshopMyTimeView Extraction

1. Create composable `useWorkshopTimesheetDay`:
   - Day data loading, selected day summary, derived state.
2. Create composable `useWorkshopTimesheetForm`:
   - Time normalization, duration math, submit/delete handlers, form state.
3. Create composable `useWorkshopCalendarSync`:
   - Calendar store sync, event creation, modal suppression loop.
4. Split template into components:
   - `WorkshopMyTimeHeader`
   - `WorkshopTimesheetSummaryCard`
   - `WorkshopTimesheetCalendar`
   - `WorkshopTimesheetLegacyTable`
   - `WorkshopTimesheetDrawer`
   - `WorkshopJobPickerDrawer`

## Phase 3: Cleanup and Consistency

- Remove duplicated lookups in templates (e.g., repeated `jobs.find` calls).
- Consolidate repeated watchers where possible using immediate watch.
- Add targeted unit tests for new composables where behavior is non-trivial.

## Acceptance Criteria

- No UI regressions in workshop views.
- Views are mostly orchestration; heavy logic lives in composables.
- New components are small, single-purpose, and typed.
- No new local API types introduced; only use `schemas` from generated API.

## Risks

- Extracting calendar behaviors may introduce subtle timing bugs.
- Attachment previews rely on browser APIs; cleanup must remain reliable.

## Test Plan

- Manual: open workshop job view and verify header, attachments, notes, stopwatch, and tables.
- Manual: open workshop my time view, add/edit/delete entries, calendar view, legacy fallback table.
- Optional: run `npx vitest --run` if new tests are added.
