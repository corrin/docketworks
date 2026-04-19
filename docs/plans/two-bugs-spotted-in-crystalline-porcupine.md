# Fix two timesheet-entry frontend bugs

## Context

Two bugs were reported from prod on the Timesheet Entry view. Both are frontend-only (Vue 3 + AG Grid), scoped to `frontend/src/` — no backend change needed.

1. **Trashcan missing on new rows.** After adding a timesheet entry, the Actions column shows no delete icon until the page is reloaded. Root cause: the AG Grid cell renderer only renders the Actions cell for rows with a backend `id`. New rows have `id: ''` and a `tempId`, so the guard returns an empty string and the delete button never mounts.
2. **Zero-hour entries vanish on reload.** If a user enters a row with 0 hours, autosave silently skips it (no toast, no error). On reload, the entry is gone because it was never POSTed. Root cause: `isRowComplete()` requires `hours > 0`, so autosave's completeness gate filters the row out at `useTimesheetAutosave.ts:170` and the backend never sees it.

Intended behaviour (confirmed with user):
- Bug 1: show the trashcan on unsaved rows. Clicking it removes the row locally (no API call) — `deleteRow()` already handles this correctly for `isNewRow` rows.
- Bug 2: persist 0-hour entries AND surface a warning toast so the user is aware the row was saved with zero hours (unusual but legitimate, e.g. cancelled meeting, non-billable visit).

---

## Bug 1 — Trashcan missing until reload

**File:** `frontend/src/composables/useTimesheetEntryGrid.ts`

### Change 1a — cell renderer guard (line 227)

Allow the renderer to mount for rows with a `tempId` as well as rows with a backend `id`.

```ts
// before
cellRenderer: (params: AgICellRendererParams) => {
  if (!params.data || !params.data.id) return ''

// after
cellRenderer: (params: AgICellRendererParams) => {
  if (!params.data || (!params.data.id && !params.data.tempId)) return ''
```

### Change 1b — onDelete handler (lines 233–241)

The handler currently bails out when `params.data.id` is falsy and looks up the grid row by `id`. For tempId-only rows it must use `tempId` as the lookup key.

```ts
// after
onDelete: () => {
  const data = params.data
  if (!data) return
  const rowId = data.id
  const tempId = data.tempId
  if (!rowId && !tempId) return
  const rowIndex = gridData.value.findIndex(
    (row: TimesheetEntryGridRow) =>
      (rowId && String(row.id) === String(rowId)) ||
      (tempId && String(row.tempId) === String(tempId)),
  )
  if (rowIndex === -1) return
  deleteRow(rowIndex)
},
```

`deleteRow()` at `useTimesheetEntryGrid.ts:759` already branches on `rowDataToRemove.isNewRow` (line 767) to clear locally without hitting the API, so no change is needed there.

---

## Bug 2 — Zero-hour entries vanishing

**File:** `frontend/src/views/TimesheetEntryView.vue`

### Change 2a — `isRowComplete` (lines 1091–1112)

Accept 0 as a valid numeric hours value. Still require the hours field to be a finite number (rejects `null`/`undefined`/`NaN`) and still require a job.

```ts
// before
isRowComplete: (e) => {
  const hasJob = Boolean(e.job_id || e.job_number || e.jobNumber)
  const hasHours = Number(e.quantity || e.hours || 0) > 0
  const isEditingDescription = isDescriptionBeingEdited(e)
  const isComplete = hasJob && hasHours && !isEditingDescription
  ...
}

// after
isRowComplete: (e) => {
  const hasJob = Boolean(e.job_id || e.job_number || e.jobNumber)
  const rawHours = e.quantity ?? e.hours
  const hoursNum = Number(rawHours)
  const hasHours =
    rawHours !== null && rawHours !== undefined && rawHours !== '' && Number.isFinite(hoursNum) && hoursNum >= 0
  const isEditingDescription = isDescriptionBeingEdited(e)
  const isComplete = hasJob && hasHours && !isEditingDescription
  ...
}
```

Note: `createNewRow()` at `useTimesheetEntryCalculations.ts:137` initialises `hours = 0`, so a freshly-added row with a job selected (but no hours yet entered) will now satisfy `isRowComplete` and autosave as a 0-hour row. This is the accepted tradeoff — the user can remove it via the trashcan (fixed in Bug 1) if unintended.

### Change 2b — warning toast on 0-hour save

In `handleSaveEntry` in `frontend/src/views/TimesheetEntryView.vue` (around line 1300 where the existing `hasJob`/`hasHours` validation lives), after the row saves successfully, if `Number(entry.quantity) === 0` show a warning toast:

```ts
toast.warning('Saved with 0 hours', { duration: 4000 })
```

Use the existing `toast` import (already used elsewhere in the file — e.g. `toast.error`, `toast.success`). Place this after the successful-save path but before the generic success handling, so the user gets the warning instead of the normal "Entry saved" message for 0-hour rows (or in addition — confirm by running it).

---

## Critical files to modify

- `frontend/src/composables/useTimesheetEntryGrid.ts` (lines 226–246) — Bug 1
- `frontend/src/views/TimesheetEntryView.vue` (lines 1091–1112, plus `handleSaveEntry` around line 1300) — Bug 2

## Existing utilities reused

- `deleteRow()` at `useTimesheetEntryGrid.ts:759` — already handles `isNewRow` rows correctly (local-only clear, no DELETE request)
- `clearRow()` at `useTimesheetEntryGrid.ts:795` — called by deleteRow to reinstate an empty template row
- `ensureEmptyRow()` — called post-delete to keep a trailing empty row in the grid
- `toast` singleton (vue-sonner) — already used throughout TimesheetEntryView.vue for save notifications

## Verification

Run frontend type-check and then manually verify in the running app (UAT / ngrok — never localhost):

1. **Bug 1:** Open Timesheet Entry, add a new row (job + hours). Before doing anything else, confirm the trashcan icon appears in the Actions column on the new row. Click it — the row should disappear and a fresh empty row should remain at the bottom. No network DELETE request should fire (check DevTools Network tab).
2. **Bug 1 regression:** For a previously-saved row, click the trashcan — a DELETE request should fire and the row should be removed.
3. **Bug 2:** Add a new row, pick a job, enter `0` in hours, wait for autosave (~500 ms debounce). Confirm a warning toast "Saved with 0 hours" appears. Reload the page — the 0-hour entry should still be present in the grid.
4. **Bug 2 regression:** Enter a row with 3 hours. Confirm normal "Entry saved" toast, no warning. Reload — entry persists.
5. **Edge case:** Add a row with just a job (no hours typed). Since `createNewRow` seeds `hours: 0`, it will now autosave as a 0-hour row with the warning toast. Verify the user can delete it via the trashcan (Bug 1 fix).
6. `cd frontend && npm run type-check` — passes.
