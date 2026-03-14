# E2E Testing Strategy

## Overview

This document outlines the comprehensive end-to-end testing strategy for the Jobs Manager application, organized by feature area with both targeted tests and a comprehensive "feature coverage" test.

## Testing Principles

### Selected Approach

- **Organization**: By feature area (separate test files per major feature)
- **Test Isolation**: Fully independent tests (each test sets up its own data)
- **Priority**: Comprehensive coverage over speed
- **Scope**: Feature coverage test touches all major features at least once

### Key Requirements

- **Database Safety**: Backup before tests, restore after (even on failure)
- **Independent Tests**: Each test can run alone or in any order
- **Parallel Execution**: Tests can run in parallel when needed
- **Comprehensive Screenshots**: Capture key screens for documentation

## Test Suite Structure

```
tests/
├── fixtures/
│   ├── auth.ts              # Authentication fixture
│   └── test-data.ts         # Helper for creating test data
├── scripts/
│   ├── backup-db.sh         # MySQL backup script
│   └── restore-db.sh        # MySQL restore script
├── helpers/
│   └── data-generators.ts   # Generate unique test data
├── features/                # Feature-based tests
│   ├── auth.spec.ts
│   ├── jobs.spec.ts
│   ├── kanban.spec.ts
│   ├── purchase-orders.spec.ts
│   ├── timesheets.spec.ts
│   ├── payroll.spec.ts
│   ├── quoting.spec.ts
│   ├── ai-chat.spec.ts
│   ├── xero-integration.spec.ts
│   ├── clients.spec.ts
│   ├── reports.spec.ts
│   └── admin.spec.ts
└── comprehensive/
    └── feature-coverage.spec.ts  # "Do everything" test
```

## Feature Test Coverage

### 1. Authentication (`auth.spec.ts`)

**Priority**: P0 (Critical)
**Complexity**: Simple
**Dependencies**: None

**Test Scenarios**:

- ✅ Login with valid credentials
- ✅ Login fails with invalid credentials
- ✅ Redirects to kanban after successful login
- ✅ Logout clears session
- ✅ Protected routes redirect to login when not authenticated

**Screenshots**:

- `auth/01-login-page.png`
- `auth/02-kanban-after-login.png`

---

### 2. Job Management (`jobs.spec.ts`)

**Priority**: P0 (Critical)
**Complexity**: Medium-Complex
**Dependencies**: Client must exist

**Test Scenarios**:

- ✅ Create new job with all required fields
- ✅ Edit existing job details
- ✅ Change job status
- ✅ Toggle job flags (quoted, invoiced, paid, rejected)
- ✅ View job detail tabs (Estimate, Quote, Actual, Cost Analysis)
- ✅ Delete job (if supported)

**Data Setup** (per test):

- Create test client
- Generate unique job name with timestamp

**Screenshots**:

- `jobs/01-job-create-form.png`
- `jobs/02-job-detail-view.png`
- `jobs/03-job-estimate-tab.png`
- `jobs/04-job-quote-tab.png`

---

### 3. Kanban Board (`kanban.spec.ts`)

**Priority**: P0 (Critical)
**Complexity**: Complex
**Dependencies**: Jobs must exist

**Test Scenarios**:

- ✅ View kanban board with jobs across status columns
- ✅ Search for specific job
- ✅ Filter jobs by staff assignment
- ✅ Drag job to different status column
- ✅ Assign staff to job from kanban
- ✅ Click job card to open detail view
- ✅ Advanced search functionality

**Data Setup** (per test):

- Create 3-5 test jobs in different statuses
- Create test staff member (optional)

**Screenshots**:

- `kanban/01-board-overview.png`
- `kanban/02-search-results.png`
- `kanban/03-advanced-search.png`
- `kanban/04-staff-filter.png`

---

### 4. Purchase Orders (`purchase-orders.spec.ts`)

**Priority**: P1 (High)
**Complexity**: Complex
**Dependencies**: Jobs may be needed for allocation

**Test Scenarios**:

- ✅ Create new purchase order
- ✅ Add line items to PO
- ✅ Edit PO details
- ✅ Allocate PO lines to job
- ✅ Allocate PO lines to stock
- ✅ Mark PO as received (partial)
- ✅ Mark PO as received (full)
- ✅ Generate PO PDF
- ✅ Email PO to supplier (if testable)

**Data Setup** (per test):

- Create test supplier (or use existing)
- Create test job for allocation
- Generate unique PO number

**Screenshots**:

- `purchase-orders/01-po-list.png`
- `purchase-orders/02-po-create.png`
- `purchase-orders/03-po-detail.png`
- `purchase-orders/04-po-allocation.png`

---

### 5. Timesheets (`timesheets.spec.ts`)

**Priority**: P0 (Critical)
**Complexity**: Medium-Complex
**Dependencies**: Staff and jobs must exist

**Test Scenarios**:

- ✅ Add timesheet entry for staff member
- ✅ Edit existing timesheet entry
- ✅ Delete timesheet entry
- ✅ Navigate between dates
- ✅ Navigate between staff members
- ✅ View daily timesheet overview
- ✅ Calculate total hours correctly (regular + overtime)
- ✅ Handle break time deductions

**Data Setup** (per test):

- Create test staff member
- Create test job
- Generate timesheet entry with unique date/time

**Screenshots**:

- `timesheets/01-entry-form.png`
- `timesheets/02-daily-overview.png`
- `timesheets/03-edit-entry.png`

---

### 6. Payroll (`payroll.spec.ts`)

**Priority**: P1 (High)
**Complexity**: Complex
**Dependencies**: Timesheets, Xero integration

**Test Scenarios**:

- ✅ View weekly timesheet overview
- ✅ Navigate between weeks
- ✅ Toggle payroll mode
- ✅ Create pay run for week (Xero)
- ✅ Post individual staff hours to Xero
- ✅ Post all staff hours to Xero (bulk)
- ✅ Refresh pay run status
- ✅ View pay run warnings/errors

**Data Setup** (per test):

- Create multiple test staff members
- Create timesheet entries for the week
- Ensure Xero connection is active

**Screenshots**:

- `payroll/01-weekly-overview.png`
- `payroll/02-payroll-mode.png`
- `payroll/03-create-payrun.png`
- `payroll/04-post-staff-hours.png`

**⚠️ Warning**: Xero operations may create real data in test environment. Consider mocking or using Xero test organization.

---

### 7. Quoting (`quoting.spec.ts`)

**Priority**: P1 (High)
**Complexity**: Medium-Complex
**Dependencies**: Job with estimates

**Test Scenarios**:

- ✅ Create quote from job estimate
- ✅ Preview quote
- ✅ Accept quote (locks for editing)
- ✅ Create quote revision
- ✅ Apply quote to job
- ✅ Link quote to job
- ✅ View cost analysis (quote vs. actual)

**Data Setup** (per test):

- Create test job with estimates
- Generate quote data

**Screenshots**:

- `quoting/01-create-quote.png`
- `quoting/02-quote-preview.png`
- `quoting/03-accept-quote.png`
- `quoting/04-cost-analysis.png`

---

### 8. AI Chat Quoting (`ai-chat.spec.ts`)

**Priority**: P2 (Medium)
**Complexity**: Complex
**Dependencies**: Job, AI provider configured

**Test Scenarios**:

- ✅ Start AI quote chat for job
- ✅ Send message to AI assistant
- ✅ Upload file (PDF or image)
- ✅ Switch between modes (quote generation, general assistance)
- ✅ AI generates quote based on conversation
- ✅ Import AI-generated quote into job

**Data Setup** (per test):

- Create test job
- Prepare test file for upload
- Mock AI responses (if possible)

**Screenshots**:

- `ai-chat/01-chat-interface.png`
- `ai-chat/02-file-upload.png`
- `ai-chat/03-generated-quote.png`
- `ai-chat/04-import-quote.png`

**⚠️ Warning**: May consume AI API credits. Consider mocking AI provider for automated tests.

---

### 9. Xero Integration (`xero-integration.spec.ts`)

**Priority**: P1 (High)
**Complexity**: Complex
**Dependencies**: Xero account credentials

**Test Scenarios**:

- ✅ Authenticate with Xero
- ✅ Start full sync
- ✅ Monitor sync progress
- ✅ View sync logs
- ✅ Create Xero invoice from job
- ✅ Delete Xero invoice
- ✅ Create Xero quote from job
- ✅ Delete Xero quote
- ✅ Disconnect Xero account

**Data Setup** (per test):

- Ensure Xero test organization is configured
- Create test job for invoice/quote creation

**Screenshots**:

- `xero/01-xero-login.png`
- `xero/02-sync-progress.png`
- `xero/03-sync-logs.png`
- `xero/04-create-invoice.png`

**⚠️ Warning**: Creates real data in Xero test organization. Requires cleanup or dedicated test org.

---

### 10. Clients & Contacts (`clients.spec.ts`)

**Priority**: P1 (High)
**Complexity**: Medium
**Dependencies**: Xero integration (optional)

**Test Scenarios**:

- ✅ Search for clients (local)
- ✅ Search for clients (Xero)
- ✅ Create new client
- ✅ View client details
- ✅ Update client information
- ✅ Add contact to client
- ✅ View client contacts
- ✅ Select contact for job

**Data Setup** (per test):

- Generate unique client name
- Generate unique contact details

**Screenshots**:

- `clients/01-client-search.png`
- `clients/02-client-create.png`
- `clients/03-client-detail.png`
- `clients/04-add-contact.png`

---

### 11. Reports (`reports.spec.ts`)

**Priority**: P2 (Medium)
**Complexity**: Medium
**Dependencies**: Jobs, timesheets, financial data

**Test Scenarios**:

- ✅ View KPI reports (monthly calendar)
- ✅ Navigate between months
- ✅ View sales forecast vs. actual
- ✅ View job aging report
- ✅ Filter job aging (include/exclude archived)
- ✅ View staff performance report
- ✅ View individual staff performance details
- ✅ View archived jobs validation report

**Data Setup** (per test):

- Create jobs with various dates and statuses
- Create timesheet entries for staff
- Create financial transactions (optional)

**Screenshots**:

- `reports/01-kpi-calendar.png`
- `reports/02-sales-forecast.png`
- `reports/03-job-aging.png`
- `reports/04-staff-performance.png`

---

### 12. Admin Features (`admin.spec.ts`)

**Priority**: P3 (Lower)
**Complexity**: Medium
**Dependencies**: Superuser authentication

**Test Scenarios**:

- ✅ Create/edit/delete staff member
- ✅ Update company defaults (hourly rates, margins)
- ✅ View application errors
- ✅ Mark errors as resolved
- ✅ Filter errors by severity
- ✅ View background jobs
- ✅ Add/edit AI provider configuration
- ✅ Set default AI provider
- ✅ Run month-end processing (if safe)
- ✅ Manage UAT environment (if applicable)

**Data Setup** (per test):

- Requires superuser credentials
- Create test staff member
- Create test AI provider config

**Screenshots**:

- `admin/01-staff-management.png`
- `admin/02-company-defaults.png`
- `admin/03-error-logs.png`
- `admin/04-ai-providers.png`

---

## Comprehensive Feature Coverage Test

### `feature-coverage.spec.ts`

**Purpose**: Touch every major feature at least once to ensure broad regression coverage
**Priority**: P0 (Critical)
**Estimated Runtime**: 10-15 minutes
**Complexity**: Very Complex

**Test Flow** (Sequential):

```typescript
test('comprehensive feature coverage - touch all major features', async ({ page }) => {
  // 1. AUTHENTICATION
  await login(page)
  await screenshot('coverage/01-login-success.png')

  // 2. KANBAN BOARD
  await navigateToKanban(page)
  await verifyKanbanLoads()
  await screenshot('coverage/02-kanban-board.png')

  // 3. CLIENT MANAGEMENT
  const client = await createClient(page)
  await screenshot('coverage/03-client-created.png')

  // 4. JOB CREATION
  const job = await createJob(page, client)
  await screenshot('coverage/04-job-created.png')

  // 5. JOB DETAIL TABS
  await navigateToJobDetail(page, job.id)
  await verifyEstimateTab()
  await screenshot('coverage/05-job-estimate.png')
  await verifyQuoteTab()
  await screenshot('coverage/06-job-quote.png')
  await verifyActualTab()
  await screenshot('coverage/07-job-actual.png')

  // 6. QUOTING
  await createQuoteFromEstimate(page, job)
  await screenshot('coverage/08-quote-created.png')

  // 7. PURCHASE ORDER
  const po = await createPurchaseOrder(page)
  await allocatePOToJob(page, po, job)
  await screenshot('coverage/09-po-created.png')

  // 8. STOCK MANAGEMENT
  await navigateToStock(page)
  await verifyStockLoads()
  await screenshot('coverage/10-stock-view.png')

  // 9. TIMESHEET ENTRY
  const staff = await createStaffMember(page)
  await createTimesheetEntry(page, staff, job)
  await screenshot('coverage/11-timesheet-entry.png')

  // 10. DAILY TIMESHEET OVERVIEW
  await navigateToDailyTimesheets(page)
  await verifyDailyOverview()
  await screenshot('coverage/12-daily-timesheets.png')

  // 11. WEEKLY TIMESHEET OVERVIEW
  await navigateToWeeklyTimesheets(page)
  await verifyWeeklyOverview()
  await screenshot('coverage/13-weekly-timesheets.png')

  // 12. PAYROLL MODE (View only, don't post to Xero)
  await togglePayrollMode(page)
  await screenshot('coverage/14-payroll-mode.png')

  // 13. XERO INTEGRATION (Status check only, don't sync)
  await navigateToXero(page)
  await verifyXeroConnectionStatus()
  await screenshot('coverage/15-xero-status.png')

  // 14. REPORTS - KPI
  await navigateToKPIReport(page)
  await verifyKPILoads()
  await screenshot('coverage/16-kpi-report.png')

  // 15. REPORTS - JOB AGING
  await navigateToJobAgingReport(page)
  await verifyJobAgingLoads()
  await screenshot('coverage/17-job-aging.png')

  // 16. REPORTS - STAFF PERFORMANCE
  await navigateToStaffPerformanceReport(page)
  await verifyStaffPerformanceLoads()
  await screenshot('coverage/18-staff-performance.png')

  // 17. ADVANCED SEARCH
  await performAdvancedSearch(page, job.name)
  await screenshot('coverage/19-advanced-search.png')

  // 18. KANBAN - DRAG AND DROP
  await navigateToKanban(page)
  await dragJobToNewStatus(page, job)
  await screenshot('coverage/20-kanban-drag-drop.png')

  // 19. ADMIN - COMPANY DEFAULTS (if superuser)
  if (isSuperuser) {
    await navigateToCompanyDefaults(page)
    await verifyCompanyDefaultsLoad()
    await screenshot('coverage/21-company-defaults.png')
  }

  // 20. LOGOUT
  await logout(page)
  await screenshot('coverage/22-logged-out.png')
})
```

**Key Characteristics**:

- **Breadth over depth**: Touches each feature briefly
- **Creates test data**: Sets up clients, jobs, POs, timesheets as needed
- **Avoids destructive operations**: No Xero posting, no month-end, no deletions
- **Screenshots everything**: 20+ screenshots for comprehensive documentation
- **Self-contained**: Creates all necessary data, doesn't rely on existing data

---

## Test Data Strategy

### Fully Independent Tests

Each test is responsible for:

1. **Creating its own test data** (clients, jobs, staff, etc.)
2. **Cleaning up implicitly** (via database restore)
3. **Using unique identifiers** (timestamps, UUIDs)

### Data Generators (`helpers/data-generators.ts`)

```typescript
export function generateUniqueJobName(): string {
  return `E2E Test Job ${Date.now()}`
}

export function generateUniqueClientName(): string {
  return `E2E Test Client ${Date.now()}`
}

export function generateUniquePONumber(): string {
  return `PO-E2E-${Date.now()}`
}

export function generateTestTimestamp(): string {
  return new Date().toISOString()
}
```

### Shared Test Fixtures (`fixtures/test-data.ts`)

```typescript
export async function createTestClient(page: Page): Promise<Client> {
  // Navigate to client creation
  // Fill form with unique data
  // Submit and return client object
}

export async function createTestJob(page: Page, client: Client): Promise<Job> {
  // Navigate to job creation
  // Fill form with unique data
  // Submit and return job object
}

export async function createTestStaff(page: Page): Promise<Staff> {
  // Navigate to staff management
  // Fill form with unique data
  // Submit and return staff object
}
```

---

## Database Backup/Restore Strategy

### Per-Test Isolation

```json
{
  "scripts": {
    "test:e2e": "bash tests/scripts/backup-db.sh && playwright test; bash tests/scripts/restore-db.sh",
    "test:e2e:single": "bash tests/scripts/backup-db.sh && playwright test --grep",
    "test:e2e:coverage": "bash tests/scripts/backup-db.sh && playwright test tests/comprehensive/; bash tests/scripts/restore-db.sh"
  }
}
```

### Backup Script (`tests/scripts/backup-db.sh`)

```bash
#!/bin/bash
set -e

# Load environment variables
source .env.test

# Create backups directory
mkdir -p tests/backups

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Backup database
mysqldump -h $MYSQL_HOST -P $MYSQL_PORT -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE > tests/backups/backup_$TIMESTAMP.sql

# Keep only last 5 backups
ls -t tests/backups/backup_*.sql | tail -n +6 | xargs rm -f

echo "Database backed up to tests/backups/backup_$TIMESTAMP.sql"
```

### Restore Script (`tests/scripts/restore-db.sh`)

```bash
#!/bin/bash
set -e

# Load environment variables
source .env.test

# Find latest backup
LATEST_BACKUP=$(ls -t tests/backups/backup_*.sql | head -n 1)

if [ -z "$LATEST_BACKUP" ]; then
  echo "No backup found! Skipping restore."
  exit 1
fi

# Restore database
mysql -h $MYSQL_HOST -P $MYSQL_PORT -u $MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE < $LATEST_BACKUP

echo "Database restored from $LATEST_BACKUP"
```

---

## Running Tests

### Environment-Specific Commands

#### Dev Environment (Full Suite with Xero)

```bash
# Run all tests including Xero integration
npm run test:e2e

# Run with UI mode for debugging
npm run test:e2e:ui

# Run in headed mode (watch browser)
npm run test:e2e:headed
```

#### UAT Environment (Full Suite with Xero)

```bash
# Run all tests against UAT
E2E_BASE_URL=https://uat-office.morrissheetmetal.co.nz npm run test:e2e
```

#### Production Environment (Full Suite WITHOUT Xero)

```bash
# Run all tests except Xero integration
npm run test:e2e:prod

# This executes: playwright test --grep-invert @xero
```

### Feature-Specific Tests

#### Single Feature Test

```bash
npm run test:e2e -- --grep "jobs"
npm run test:e2e -- --grep "kanban"
npm run test:e2e -- --grep "timesheets"
```

#### Coverage Test Only

```bash
npm run test:e2e:coverage
```

### Test Tags

Tests are tagged for environment-specific execution:

- **`@xero`** - Xero integration tests (skipped in production)
- **`@mutation`** - Data mutation tests (runs in all environments)
- **`@readonly`** - Read-only tests (runs in all environments)

```bash
# Run only Xero tests (dev/UAT only)
npm run test:e2e -- --grep @xero

# Run only read-only tests
npm run test:e2e -- --grep @readonly

# Skip Xero tests (production)
npm run test:e2e -- --grep-invert @xero
```

---

## Test Execution Order

### Recommended Run Sequence

1. **Authentication test first** (validates login works)
2. **Feature tests in dependency order**:
   - Clients (no dependencies)
   - Jobs (needs clients)
   - Kanban (needs jobs)
   - Timesheets (needs staff and jobs)
   - Purchase Orders (needs jobs for allocation)
   - Quoting (needs jobs with estimates)
   - Payroll (needs timesheets)
   - Xero Integration (needs various data)
   - Reports (needs various data)
3. **Admin tests last** (cleanup, configuration)
4. **Comprehensive coverage test** (runs everything)

### Parallel Execution

Tests can run in parallel since they're fully independent:

```bash
npx playwright test --workers=4
```

**Warning**: Parallel execution requires careful database backup/restore coordination. Recommend sequential execution for initial implementation.

---

## Success Criteria

### Per-Feature Test

- ✅ All test scenarios pass
- ✅ Screenshots generated for key screens
- ✅ Database restored after test
- ✅ No data pollution (unique identifiers used)
- ✅ Test runs independently (no dependency on other tests)

### Comprehensive Coverage Test

- ✅ Touches all 18+ major features
- ✅ Completes in under 15 minutes
- ✅ Generates 20+ screenshots
- ✅ Creates all necessary test data
- ✅ Database restored after completion
- ✅ Can run standalone without other tests

### Overall Test Suite

- ✅ 100+ test scenarios across all features
- ✅ 80%+ code coverage (aspirational)
- ✅ All P0 and P1 tests passing
- ✅ Comprehensive screenshot library for documentation
- ✅ Reliable and repeatable (no flaky tests)

---

## Maintenance & Evolution

### Adding New Tests

1. Identify feature area
2. Create test file in appropriate directory
3. Use existing fixtures for auth and data setup
4. Follow naming conventions
5. Add screenshots to relevant directory
6. Update this strategy document

### Test Data Cleanup

- Database restore handles all cleanup
- No manual cleanup required
- Test data uses unique identifiers to avoid conflicts

### CI/CD Integration (Future)

- Run comprehensive coverage test on every PR
- Run full test suite before release
- Generate screenshot diff reports
- Track test execution time trends

---

## Estimated Implementation Timeline

| Feature Area      | Test File                  | Estimated Time | Priority |
| ----------------- | -------------------------- | -------------- | -------- |
| Authentication    | `auth.spec.ts`             | 1 hour         | P0       |
| Jobs              | `jobs.spec.ts`             | 2 hours        | P0       |
| Kanban            | `kanban.spec.ts`           | 2.5 hours      | P0       |
| Timesheets        | `timesheets.spec.ts`       | 2 hours        | P0       |
| Purchase Orders   | `purchase-orders.spec.ts`  | 2.5 hours      | P1       |
| Quoting           | `quoting.spec.ts`          | 1.5 hours      | P1       |
| Payroll           | `payroll.spec.ts`          | 2 hours        | P1       |
| Clients           | `clients.spec.ts`          | 1.5 hours      | P1       |
| Xero Integration  | `xero-integration.spec.ts` | 2 hours        | P1       |
| Reports           | `reports.spec.ts`          | 2 hours        | P2       |
| AI Chat           | `ai-chat.spec.ts`          | 2 hours        | P2       |
| Admin             | `admin.spec.ts`            | 1.5 hours      | P3       |
| **Coverage Test** | `feature-coverage.spec.ts` | **4 hours**    | **P0**   |
| **TOTAL**         |                            | **~27 hours**  |          |

### Phased Rollout

**Phase 1 (MVP - 4 hours)**:

- Comprehensive coverage test only
- Touches all features briefly
- Provides baseline regression protection

**Phase 2 (Core Features - 8 hours)**:

- Auth, Jobs, Kanban, Timesheets tests
- Critical path coverage

**Phase 3 (Extended Features - 10 hours)**:

- Purchase Orders, Quoting, Payroll, Clients, Xero
- High-value feature coverage

**Phase 4 (Complete Suite - 5 hours)**:

- Reports, AI Chat, Admin tests
- Full comprehensive coverage

---

## Testing Approach Decisions

### ✅ Confirmed Testing Strategy

1. **Xero Testing**: ✅ Test against **Xero Demo Company** (real integration, dev/UAT only)

   - All Xero operations will execute against demo company in dev/UAT
   - Creates real invoices, quotes, POs, pay runs in Xero demo
   - Provides authentic integration testing
   - **Production: Xero tests are SKIPPED** (tagged with `@xero`)

2. **AI Chat Testing**: ✅ Test with **real AI provider** (no mocking)

   - Actual API calls to Claude/Gemini/Mistral
   - Will consume API credits (acceptable for comprehensive testing)
   - Validates real-world AI integration behavior
   - Runs in all environments (dev, UAT, production)

3. **File Uploads**: ✅ **Practice files available** for testing

   - Test with real PDFs, images, DWG, DXF files
   - Validates file processing pipeline end-to-end
   - Runs in all environments

4. **Email Testing**: ✅ Test using **real SMTP server**

   - Actual emails sent (to test addresses)
   - Validates email formatting and delivery
   - Confirms supplier PO emails work correctly
   - Runs in all environments

5. **Performance**: ✅ **Nice-to-have bonus** (not primary focus)

   - Add basic performance assertions where easy (e.g., page load times)
   - Track regression in critical paths
   - Don't block on performance optimization

6. **Visual Regression**: ✅ **Nice-to-have bonus** (not primary focus yet)

   - Screenshots captured for all features
   - Can diff against old screenshots manually or with tools later
   - Foundation for future visual regression testing

7. **Mobile Testing**: ✅ **Nice-to-have bonus** (not primary focus)
   - Primary focus on desktop viewports
   - Can add mobile viewports later if time permits
   - Some views have mobile variants (kanban)

### Multi-Environment Testing Strategy

#### **Dev Environment** - Full Suite with Xero

- **Target**: Dev ngrok URLs or localhost
- **Database**: Dev MySQL database
- **Xero**: Demo company (all operations allowed)
- **Test Suite**: All tests including `@xero` tagged tests
- **Data Cleanup**: Database backup/restore after run
- **Command**: `npm run test:e2e`

#### **UAT Environment** - Full Suite with Xero (Pre-release validation)

- **Target**: `https://uat-office.morrissheetmetal.co.nz`
- **Database**: UAT MySQL database
- **Xero**: Demo/test company (all operations allowed)
- **Test Suite**: All tests including `@xero` tagged tests
- **Data Cleanup**: Database backup/restore after run
- **Command**: `E2E_BASE_URL=https://uat-office.morrissheetmetal.co.nz npm run test:e2e`

#### **Production (PVT)** - Full Suite WITHOUT Xero

- **Target**: `https://office.morrissheetmetal.co.nz`
- **Database**: Production MySQL database
- **Xero**: **SKIPPED** - No Xero operations to avoid impacting real accounting data
- **Test Suite**: All tests EXCEPT `@xero` tagged tests
- **Data Cleanup**: Database backup/restore after run (critical!)
- **Command**: `npm run test:e2e:prod`
- **Safety**: Database restore ensures no permanent data pollution in production

**Production Testing Philosophy**:

- ✅ Test all application features (jobs, POs, timesheets, quotes, etc.)
- ✅ Validate UI workflows work correctly in production
- ✅ Database backup/restore ensures clean slate after testing
- ❌ Skip Xero integration tests to avoid polluting real accounting system
- ❌ No permanent data changes (backup/restore handles cleanup)

---

## Next Steps

1. ✅ Review and approve this testing strategy
2. ⏳ Implement Phase 1 (Comprehensive coverage test - 4 hours)
3. ⏳ Validate Phase 1 success criteria
4. ⏳ Plan Phase 2 implementation
5. ⏳ Iterate and refine based on learnings
