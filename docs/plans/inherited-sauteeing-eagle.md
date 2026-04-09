# Fix: E2E flaky tests and teardown observability

## Context

Two E2E issues found:

1. **"add Adjustment entry" test targets wrong row ~1 in 4 runs.** `SmartCostLinesTable` always appends a permanent `emptyLine` to `displayLines`. `rows.last()` grabs that instead of the phantom created by `clickAddRow`.

2. **DB teardown silently fails to restore.** `psql` stderr is captured but never logged. When restore partially fails, the next run hits "34 test clients found" with no diagnostic info.

## Fix 1: Stable row IDs for test targeting

### 1a. Add `data-row-id` to DataTable rows

**File:** `frontend/src/components/DataTable.vue` (already done)

`DataTable` already computes a stable row ID via `getRowId: (row) => row.id || row.__localId || 'local-${index}'`. Add `:data-row-id="row.id"` to the `<TableRow>`.

### 1b. `clickAddRow` returns new row's stable ID

**File:** `frontend/tests/job/create-estimate-entry.spec.ts` (already done)

Snapshot existing `data-row-id` values before click, wait for count to increase, find the new one.

### 1c. `addAdjustmentEntry` uses stable ID

**File:** `frontend/tests/job/create-estimate-entry.spec.ts` (already done)

Use `getRowById(page, rowId)` instead of `rows.last()`. Tab navigation preserved — still tests real user flow.

## Fix 2: Log psql stderr in teardown

**File:** `frontend/tests/scripts/global-teardown.ts`

Always log stderr from the psql restore so we have data next time something goes wrong. Don't try to interpret it — just make it visible.

```ts
const stderr = result.stderr?.toString() || ''
if (stderr) {
  console.log('[db] psql restore output:', stderr)
}
if (result.status !== 0) {
  throw new Error(`Database restore failed (exit code ${result.status})`)
}
```

## Fix 3: Other already-applied fixes (keep)

- `apps/job/serializers/job_serializer.py` — `AssignJobResponseSerializer`: make `message` optional, add `error` field
- `apps/job/views/assign_job_view.py` — add warning log on assignment failure
- `frontend/tests/scripts/e2e-reset.ts` — fix `__dirname` in ESM

## Files to modify

- `frontend/src/components/DataTable.vue` — already done
- `frontend/tests/job/create-estimate-entry.spec.ts` — already done
- `frontend/tests/scripts/global-teardown.ts` — log psql stderr
- `apps/job/serializers/job_serializer.py` — already done
- `apps/job/views/assign_job_view.py` — already done
- `frontend/tests/scripts/e2e-reset.ts` — already done

## Verification

Run the adjustment test repeatedly:
```
npx playwright test tests/job/create-estimate-entry.spec.ts -g "add Adjustment entry" --repeat-each=4
```

Then full E2E suite:
```
npx playwright test --max-failures=1
```
