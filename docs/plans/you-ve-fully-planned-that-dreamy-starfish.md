# Stop silently dropping incomplete timesheet rows

## Context

User types job `8` on a fresh row, leaves Hours at 0, moves on. The entry is dropped without any signal. Django log is empty because the save was never attempted: the gate at `frontend/src/composables/useTimesheetEntryGrid.ts:442` calls `isRowComplete` (line 733), which requires `hours > 0`, and silently returns. The user's uncommitted `>= 0` relaxation in `TimesheetEntryView.vue` is unreachable — the composable gate dropped the row before the view ever sees it.

Decisions confirmed with the user:
- Keep `hours > 0` as the save rule. **Revert the uncommitted `>= 0` change.**
- Fix the silence with two cues: a continuous visual (amber row) plus a toast at the transition that actually loses data (switching staff or date).
- Do **not** touch Enter (ambiguous with normal "stage next row" flow) or add a route guard (would interact with unverified autosave-pending handling).

## Changes

### 1. `frontend/src/composables/useTimesheetEntryGrid.ts`

**a. `getRowStyle` (line 287) — split the new-row branch.**

Read raw row fields directly. Do **not** call `createEntryFromRowData` from here — it mutates `meta` and `console.log`s (line 617), which would fire on every grid render.

```ts
getRowStyle: (params) => {
  if (!params.data) return undefined
  if (!params.data.isNewRow) return undefined

  const hasJob = Boolean(params.data.jobNumber || params.data.job_number)
  const hours = Number(params.data.hours ?? params.data.quantity ?? 0)
  const description = String(params.data.description ?? params.data.desc ?? '').trim()
  const isEmpty = !hasJob && hours === 0 && !description
  const isComplete = hasJob && hours > 0

  if (!isEmpty && !isComplete) {
    return { backgroundColor: '#FFFBEB', border: '1px dashed #F59E0B' }  // amber — won't save
  }
  return { backgroundColor: '#F0F9FF', border: '1px dashed #3B82F6' }    // blue — draft placeholder (existing)
}
```

**b. Export `getIncompleteDraftRows()`** — pure function, walks `gridData.value`, returns rows matching the same `!isEmpty && !isComplete && isNewRow` predicate. Reads fields directly, no side effects. Added to the returned object from `useTimesheetEntryGrid` at line 974.

### 2. `frontend/src/views/TimesheetEntryView.vue`

**a. Revert the uncommitted `>= 0` diffs:**
- `isRowComplete` callback (lines 1094–1097) → `const hasHours = Number(e.quantity || e.hours || 0) > 0`.
- `handleSaveEntry` validation (lines 1279–1282) → `const hasHours = Number(entryRow.quantity ?? 0) > 0`.
- Delete the `if (hoursNum === 0) toast.warning('Saved with 0 hours', …)` block at lines 1403–1405.

**b. Toast on staff/date navigation.** In `navigateStaff` (line 1149), `navigateDate` (line 1162), and `goToToday` (line 1195), before any state change, call the helper and toast each incomplete draft:

```ts
const drafts = getIncompleteDraftRows()
for (const row of drafts) {
  const jobPart = row.jobNumber || row.job_number
    ? `job ${row.jobNumber || row.job_number}`
    : '(no job)'
  const missing = !(row.jobNumber || row.job_number) ? 'a job number' : 'hours'
  toast.warning(`Entry for ${jobPart} not saved — needs ${missing}`, { duration: 6000 })
}
```

`toast` from `vue-sonner` is already imported in both files. The toaster is mounted at app level, so toasts survive the route change.

## Files

- `frontend/src/composables/useTimesheetEntryGrid.ts` — split `getRowStyle` (line 287), add `getIncompleteDraftRows` export.
- `frontend/src/views/TimesheetEntryView.vue` — revert `>=0` diffs, call helper from three nav handlers.

## What this explicitly does not do

- No change to `handleCellValueChanged` — per-keystroke toasts would nag normal entry.
- No change to Enter in `handleCellKeyDown` — Enter means "next row", not "commit".
- No `onBeforeRouteLeave` guard — interaction with existing autosave pending-state is unverified.
- No change to the `isRowComplete` gate at line 733 — keeping `hours > 0`.

If the nav-toast turns out to be insufficient (e.g. user navigates via sidebar route link without passing through these handlers), route-guard scope can be added later with time to verify.

## Verification (manual, pre-prod)

1. Fresh row, type job `8`, Tab out of Hours with value `0`. Row turns amber-dashed. No toast.
2. Click next staff. Toast: `Entry for job 8 not saved — needs hours`. View reloads.
3. Come back to the original staff/date. The amber row is gone (not saved, as intended).
4. Type job `8`, hours `3`. Row saves; Django log shows the POST. No toast. Styling reverts.
5. Completely empty trailing row: stays blue-dashed, no toast on nav.
6. Row with description but no job/hours: amber, toast on nav: `Entry for (no job) not saved — needs a job number`.
7. `npm run type-check` passes.
