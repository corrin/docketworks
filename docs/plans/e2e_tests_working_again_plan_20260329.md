# Fix Playwright E2E Test Failures

## Context
27 of 77 Playwright tests fail because the database has stale test data from previous runs. The backup/restore cycle can't recover from a skipped teardown — once dirty data is captured in a backup, every subsequent restore reproduces it.

E2E tests run in production as PVT. The reset must be production-safe — it must never delete real data.

## Design

### 1. Standardize test data naming: `[TEST]` prefix

All test-created entities (jobs, contacts, clients, POs, staff) must be prefixed with `[TEST]`. This makes test data identifiable in any environment including production.

**Files to update:**
- `frontend/tests/fixtures/helpers.ts` — `createTestJob()`, `createTestPurchaseOrder()`, `TEST_CLIENT_NAME`
- `frontend/tests/fixtures/auth.ts` — `sharedEditJobUrl` fixture (job name, contact name)
- `frontend/tests/job/create-job.spec.ts` — hardcoded contact names ("Test Contact Person" → "[TEST] Contact Person")
- `frontend/tests/job/create-job-with-new-client.spec.ts` — client names ("E2E Test Client" → "[TEST] Client")
- `frontend/tests/staff/create-staff.spec.ts` — staff names
- Any other test files that create data with non-prefixed names

The `[TEST]` prefix is used for:
- Safety: reset script only deletes `[TEST]`-prefixed items
- Visibility: test data is obvious in any UI or database

### 2. Read-only safety checks in global-setup (abort if dirty)

**File: `frontend/tests/scripts/global-setup.ts`**

Before backup, run read-only checks:
- **Xero**: Verify Xero connection is active (read-only API check, NOT `ensureXeroConnected`)
- **Test data**: No `[TEST]`-prefixed items exist in the database (jobs, contacts, clients)
- **Sequences**: All sequences are in sync

If any check fails, abort with a clear message telling the user what's wrong and how to fix it.

Checks MUST NOT change state. They only read and report.

### 3. Reset command (explicit, deliberate, production-safe)

**Two parts:**

**Part A: Django management command for safe deletion**
**File: `apps/workflow/management/commands/e2e_cleanup.py`**

Uses Django ORM's `QuerySet.delete()` which handles FK cascades correctly. No raw SQL delete fights.

- `--dry-run` (default): prints what would be deleted, exits 0
- `--confirm`: actually deletes, prints counts
- Deletes: `[TEST]`-prefixed jobs, contacts, clients + legacy `E2E`-prefixed clients + all data on test client
- Production safe: ORM cascade handles all FK dependencies automatically

**Part B: Node script for the full reset flow**
**File: `frontend/tests/scripts/e2e-reset.ts`**

Orchestrates:
1. Calls `python manage.py e2e_cleanup --dry-run` (or `--confirm`)
2. Syncs sequences
3. Takes a fresh clean backup

**package.json:** `"test:e2e:reset": "npx tsx tests/scripts/e2e-reset.ts"`

### 4. Keep sequence sync in global-setup

The sequence sync stays as a lightweight safety net (idempotent, fast).

### 5. Teardown stays as-is

Existing restore-from-backup teardown continues working. Safety check in setup catches skipped teardowns.

### 6. Default to --max-failures=1

Already done: `"test:e2e": "playwright test --max-failures=1"` stops on first failure.

## Key Files to Create/Modify
- `apps/workflow/management/commands/e2e_cleanup.py` — NEW: Django management command for safe test data deletion
- `frontend/tests/fixtures/helpers.ts` — add `[TEST]` prefix to all test data creation (DONE)
- `frontend/tests/fixtures/auth.ts` — prefix in sharedEditJobUrl fixture (DONE)
- `frontend/tests/job/create-job.spec.ts` — prefix contact/job names (DONE)
- `frontend/tests/job/create-job-with-new-client.spec.ts` — prefix client names (DONE)
- `frontend/tests/staff/create-staff.spec.ts` — prefix staff names (DONE)
- `frontend/tests/scripts/global-setup.ts` — read-only safety checks (DONE)
- `frontend/tests/scripts/global-teardown.ts` — preserve Xero token across restore (DONE)
- `frontend/tests/scripts/e2e-reset.ts` — rewrite to call Django management command
- `frontend/tests/scripts/db-backup-utils.ts` — shared constants and check functions (DONE)
- `frontend/package.json` — `test:e2e:reset` script (DONE)

## Verification
1. With dirty DB: `npm run test:e2e` aborts with clear message
2. `npm run test:e2e:reset` shows dry-run of what would be deleted
3. `npm run test:e2e:reset --confirm` cleans test data, takes backup
4. `npm run test:e2e` passes safety checks, runs tests, stops on first failure
5. After normal run: teardown restores DB, next run passes safety checks
