# E2E Testing - Multi-Environment Strategy

## Quick Reference

| Environment    | Xero Tests  | Database        | Cleanup        | Command                                                          |
| -------------- | ----------- | --------------- | -------------- | ---------------------------------------------------------------- |
| **Dev**        | ✅ Included | Dev PostgreSQL  | Backup/Restore | `npm run test:e2e`                                               |
| **UAT**        | ✅ Included | UAT PostgreSQL  | Backup/Restore | `E2E_BASE_URL=https://msm-uat.docketworks.site npm run test:e2e` |
| **Production** | ❌ Skipped  | Prod PostgreSQL | Backup/Restore | `npm run test:e2e:prod`                                          |

## Environment Details

### Dev Environment

**Purpose**: Daily development testing

**What runs**:

- ✅ All feature tests (jobs, POs, timesheets, kanban, etc.)
- ✅ Xero integration tests (invoices, quotes, POs, payroll)
- ✅ AI chat tests (real API calls)
- ✅ Email tests (real SMTP)
- ✅ File upload tests

**Target**:

- Dev URL: `https://docketworks-msm-dev.ngrok-free.app` (or localhost:5173)
- Vite proxies `/api` to Django on localhost:8000 (single tunnel)

**Xero**: Demo company (safe to pollute)

**Database**: Dev PostgreSQL - backed up before tests, restored after

**Command**:

```bash
npm run test:e2e
```

---

### UAT Environment

**Purpose**: Pre-release validation before production deployment

**What runs**:

- ✅ All feature tests (same as dev)
- ✅ Xero integration tests
- ✅ AI chat tests
- ✅ Email tests
- ✅ File upload tests

**Target**:

- Frontend/Backend: `https://msm-uat.docketworks.site`

**Xero**: Demo/test company (safe to pollute)

**Database**: UAT PostgreSQL - backed up before tests, restored after

**Command**:

```bash
E2E_BASE_URL=https://msm-uat.docketworks.site npm run test:e2e
```

---

### Production Environment (PVT - Production Verification Testing)

**Purpose**: Verify production deployment works correctly

**What runs**:

- ✅ All feature tests (jobs, POs, timesheets, kanban, etc.)
- ✅ AI chat tests (real API calls)
- ✅ Email tests (real SMTP)
- ✅ File upload tests
- ❌ **Xero tests SKIPPED** (to avoid polluting real accounting data)

**Target**:

- Frontend/Backend: `https://office.morrissheetmetal.co.nz`

**Xero**: **Not touched** - all `@xero` tagged tests are skipped

**Database**: Production PostgreSQL - backed up before tests, **restored after** (critical!)

**Command**:

```bash
npm run test:e2e:prod
```

**Safety Measures**:

1. Database backup before any tests run
2. All tests create data with unique identifiers (timestamps)
3. Database restore after tests complete (even if tests fail)
4. No Xero operations (real accounting data protected)

---

## Test Tagging System

### `@xero` Tag

Applied to any test that interacts with Xero:

- Creating/deleting invoices in Xero
- Creating/deleting quotes in Xero
- Creating/deleting POs in Xero
- Posting payroll to Xero
- Syncing data with Xero

**Execution**:

- ✅ Runs in Dev
- ✅ Runs in UAT
- ❌ **Skipped in Production** (via `--grep-invert @xero`)

**Example**:

```typescript
test('post job invoice to Xero', { tag: '@xero' }, async ({ page }) => {
  // This test will NOT run in production
})
```

### `@mutation` Tag

Applied to tests that modify data (but not Xero):

- Creating jobs, POs, timesheets
- Editing data
- Deleting records

**Execution**:

- ✅ Runs in all environments (dev, UAT, production)
- Database backup/restore handles cleanup

**Example**:

```typescript
test('create new job', { tag: '@mutation' }, async ({ page }) => {
  // Runs in all environments, cleaned up by database restore
})
```

### `@readonly` Tag

Applied to tests that only read data:

- Viewing reports
- Searching
- Navigating between views

**Execution**:

- ✅ Runs in all environments
- Safest tests for production

**Example**:

```typescript
test('view KPI report', { tag: '@readonly' }, async ({ page }) => {
  // Safe to run anywhere
})
```

---

## Database Backup/Restore Strategy

### How It Works

```
┌─────────────────────────────────────────┐
│  1. Backup Database (before tests)      │
│     pg_dump > backup_20250124.sql     │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  2. Run E2E Tests                        │
│     - Create jobs, POs, timesheets       │
│     - Test all features                  │
│     - Generate screenshots               │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  3. Restore Database (after tests)       │
│     psql< backup_20250124.sql         │
│     (Runs even if tests fail!)          │
└─────────────────────────────────────────┘
```

### Backup Script Location

`tests/scripts/backup-db.sh`

### Restore Script Location

`tests/scripts/restore-db.sh`

### Backup Storage

`tests/backups/` (not committed to git)

- Keeps last 5 backups
- Older backups auto-deleted

### Environment Variables Required

```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=dw_msm_dev
DB_USER=your_user
DB_PASSWORD=your_password
```

---

## npm Scripts

### package.json Scripts

```json
{
  "scripts": {
    "test:e2e": "bash tests/scripts/backup-db.sh && playwright test; STATUS=$?; bash tests/scripts/restore-db.sh; exit $STATUS",
    "test:e2e:prod": "bash tests/scripts/backup-db.sh && playwright test --grep-invert @xero; STATUS=$?; bash tests/scripts/restore-db.sh; exit $STATUS",
    "test:e2e:ui": "playwright test --ui",
    "test:e2e:headed": "playwright test --headed",
    "test:e2e:coverage": "bash tests/scripts/backup-db.sh && playwright test tests/comprehensive/; STATUS=$?; bash tests/scripts/restore-db.sh; exit $STATUS"
  }
}
```

### Key Features

- Backup **always** runs before tests
- Restore **always** runs after tests (even if tests fail)
- Exit code preserved so CI/CD knows if tests passed/failed

---

## Running Tests by Feature

You can run specific feature tests in any environment:

### Jobs

```bash
npm run test:e2e -- --grep "jobs"
```

### Purchase Orders (including Xero in dev/UAT)

```bash
npm run test:e2e -- --grep "purchase-orders"
```

### Purchase Orders (excluding Xero in production)

```bash
npm run test:e2e:prod -- --grep "purchase-orders"
```

### Timesheets

```bash
npm run test:e2e -- --grep "timesheets"
```

### Payroll (including Xero posting in dev/UAT)

```bash
npm run test:e2e -- --grep "payroll"
```

### Payroll (excluding Xero posting in production)

```bash
npm run test:e2e:prod -- --grep "payroll"
```

---

## Production Testing Philosophy

### Why test in production?

- Verify deployment succeeded
- Catch environment-specific issues
- Validate real infrastructure works
- Confidence in production health

### Why skip Xero in production?

- Xero contains real accounting data
- Creating/deleting invoices would pollute real financials
- Risk of impacting actual customer invoices
- Compliance and audit trail concerns

### Is it safe to test in production?

**Yes**, because:

1. ✅ Database backup/restore ensures no permanent data changes
2. ✅ Test data uses unique identifiers (timestamps)
3. ✅ No Xero operations (real accounting protected)
4. ✅ Tests run quickly (10-15 minutes)
5. ✅ Can schedule during low-traffic periods

### What about emails in production?

- Configure test email addresses in production environment
- Emails still sent but to test recipients only
- Validates SMTP configuration works in production

---

## CI/CD Integration (Future)

### Recommended Pipeline

```yaml
# Example GitHub Actions workflow
on:
  pull_request:
    branches: [main]

jobs:
  e2e-uat:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
      - run: npm install
      - run: npx playwright install chromium
      - run: E2E_BASE_URL=https://msm-uat.docketworks.site npm run test:e2e
        env:
          E2E_TEST_USERNAME: ${{ secrets.E2E_TEST_USERNAME }}
          E2E_TEST_PASSWORD: ${{ secrets.E2E_TEST_PASSWORD }}
          DB_HOST: ${{ secrets.UAT_DB_HOST }}
          DB_USER: ${{ secrets.UAT_DB_USER }}
          DB_PASSWORD: ${{ secrets.UAT_DB_PASSWORD }}

  deploy-prod:
    needs: e2e-uat
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        run: ./deploy.sh

  e2e-prod-pvt:
    needs: deploy-prod
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
      - run: npm install
      - run: npx playwright install chromium
      - run: npm run test:e2e:prod # Skips Xero tests
        env:
          E2E_BASE_URL: https://office.morrissheetmetal.co.nz
          E2E_TEST_USERNAME: ${{ secrets.E2E_TEST_USERNAME }}
          E2E_TEST_PASSWORD: ${{ secrets.E2E_TEST_PASSWORD }}
          DB_HOST: ${{ secrets.PROD_DB_HOST }}
          DB_USER: ${{ secrets.PROD_DB_USER }}
          DB_PASSWORD: ${{ secrets.PROD_DB_PASSWORD }}
```

---

## Troubleshooting

### "Database restore failed"

- Check PostgreSQL credentials in `.env.test`
- Ensure backup file exists in `tests/backups/`
- Verify PostgreSQL user has restore permissions

### "Tests fail in production but pass in dev"

- Check environment-specific configuration
- Verify production URLs are correct
- Ensure test user exists in production
- Check Xero tests are skipped (should use `npm run test:e2e:prod`)

### "Xero tests run in production"

- Must use `npm run test:e2e:prod` (not `npm run test:e2e`)
- Check tests are properly tagged with `@xero`

### "Performance is slow in production"

- Production tests may be slower (real infrastructure)
- Consider running during low-traffic periods
- Can increase timeouts in `playwright.config.ts`

---

## Summary

| ✅ DO in Production        | ❌ DON'T in Production       |
| -------------------------- | ---------------------------- |
| Create test jobs           | Post to real Xero            |
| Create test POs            | Skip database restore        |
| Create test timesheets     | Use real client data         |
| Test AI chat               | Run during peak hours        |
| Send test emails           | Forget `--grep-invert @xero` |
| Run comprehensive coverage | Skip backup script           |

**Golden Rule**: Production tests should be **indistinguishable** from dev/UAT tests, except Xero operations are skipped and database is always restored.
