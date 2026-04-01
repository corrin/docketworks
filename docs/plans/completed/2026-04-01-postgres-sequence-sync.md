# Fix: syncSequences misses identity column sequences after pg_dump restore

## Context

E2E tests fail with `IntegrityError` on `workflow_historicaljob_pkey` because the custom `syncSequences` SQL query misses identity column sequences (all SimpleHistory tables, plus 15 others). Django already has `manage.py sqlsequencereset` that handles all sequence types correctly.

## Fix

**File:** `frontend/tests/scripts/db-backup-utils.ts` — `syncSequences` function (line 123-150)

Replace the custom `pg_depend`-based SQL with a call to `manage.py sqlsequencereset` piped into `psql`. Delete the hand-rolled query entirely.

The function needs to:
1. Get all Django app labels
2. Run `manage.py sqlsequencereset <apps>` to generate the SQL
3. Pipe that SQL into `psql`

Or simpler: just run `manage.py sqlsequencereset` for all installed apps via `spawnSync`, capture the SQL output, and pass it to `runPsql`.

## Verification

1. Run `cd frontend && npx playwright test tests/job/create-estimate-entry.spec.ts`
2. Job creation should succeed (no 409/IntegrityError)
