# E2E Testing Implementation Plan

## Overview

This document outlines the implementation plan for adding end-to-end (E2E) regression testing with automated screenshot generation to the Vue + Django workflow application.

## Refined Approach

Based on codebase analysis and requirements:

- **Core Flow**: Job creation with database backup/restore safety net
- **Framework**: Playwright (fresh installation)
- **Screenshots**: Generated to `docs_screens/` but not committed (added to .gitignore)
- **Authentication**: Existing test user credentials via environment variables
- **Database Safety**: MySQL backup before tests, restore after (even on failure)

## Implementation Steps

### 1. Install & Configure Playwright (30 min)

**Actions:**

- Run `npm init playwright@latest`
  - Choose TypeScript
  - Use `tests/` folder
  - Install browsers
- Create `playwright.config.ts` with:
  - Base URL from environment variable (defaults to ngrok frontend)
  - 60s timeout for operations
  - Headless mode enabled
  - Screenshot configuration
- Add test scripts to `package.json`:
  ```json
  {
    "scripts": {
      "test:e2e": "bash tests/scripts/backup-db.sh && playwright test; bash tests/scripts/restore-db.sh",
      "test:e2e:ui": "playwright test --ui",
      "test:e2e:headed": "playwright test --headed"
    }
  }
  ```

**Deliverables:**

- `playwright.config.ts` configured
- Playwright installed in `node_modules`
- Test scripts added to `package.json`

### 2. Database Safety Wrapper (45 min)

**Actions:**

- Create `tests/scripts/backup-db.sh`:
  - MySQL dump with timestamp
  - Store in `tests/backups/`
  - Use credentials from environment variables
- Create `tests/scripts/restore-db.sh`:
  - Restore from latest backup
  - Clean up old backups (keep last 5)
- Ensure scripts are executable (`chmod +x`)
- Add `tests/backups/` to `.gitignore`
- Update npm script to chain: backup → test → restore

**Deliverables:**

- `tests/scripts/backup-db.sh`
- `tests/scripts/restore-db.sh`
- `tests/backups/` directory created and ignored
- Composite npm command that ensures restore runs even on test failure

### 3. Auth Fixture (30 min)

**Actions:**

- Create `tests/fixtures/auth.ts`:
  - Extend Playwright's base test
  - Provide `authenticatedPage` fixture
  - Handle login flow:
    - Navigate to `/login`
    - Fill username/email field (`#username`)
    - Fill password field (`#password`)
    - Click "Sign In" button
    - Wait for redirect to `/kanban`
  - Use test credentials from environment variables
  - Store bearer token in localStorage

**Deliverables:**

- `tests/fixtures/auth.ts` with reusable authenticated page fixture
- Login flow abstracted for all tests

### 4. Job Creation Test (1.5 hours)

**Actions:**

- Create `tests/job-creation.spec.ts`:
  - Import authenticated page fixture
  - Test flow:
    1. Start at Kanban board (post-login)
    2. Screenshot: `01-kanban-after-login.png`
    3. Click "New Job" or navigate to `/jobs/create`
    4. Screenshot: `02-job-creation-form.png`
    5. Fill required fields:
       - Job name: `E2E Test Job ${timestamp}`
       - Client selection (lookup/select)
       - Estimated materials
       - Estimated hours
    6. Click Save/Submit
    7. Screenshot: `03-job-detail-page.png`
    8. Navigate back to Kanban/jobs list
    9. Search for created job name
    10. Screenshot: `04-job-in-list.png`
    11. Assert job appears in results
- Use robust selectors:
  - Prefer `getByRole()`, `getByLabel()`, `getByText()`
  - Avoid brittle CSS selectors
- Handle async operations with proper waits:
  - Use `waitForURL()`, `waitForSelector()`
  - Avoid hardcoded `waitForTimeout()` where possible

**Deliverables:**

- `tests/job-creation.spec.ts` with complete smoke test
- 4 screenshots generated to `docs_screens/`
- Test validates end-to-end data persistence

### 5. Environment & Documentation (30 min)

**Actions:**

- Add to `.gitignore`:
  ```
  docs_screens/
  tests/backups/
  .env.test
  ```
- Create `.env.test.example`:
  ```
  E2E_BASE_URL=https://msm-workflow-front.ngrok-free.app
  E2E_TEST_USERNAME=your-test-user@example.com
  E2E_TEST_PASSWORD=your-secure-password
  MYSQL_HOST=localhost
  MYSQL_PORT=3306
  MYSQL_DATABASE=msm_workflow
  MYSQL_USER=your-db-user
  MYSQL_PASSWORD=your-db-password
  ```
- Create `docs/e2e-testing.md`:
  - Prerequisites
  - Environment setup instructions
  - How to run tests
  - Database backup/restore explanation
  - Screenshot location and usage
  - Troubleshooting tips

**Deliverables:**

- `.gitignore` updated
- `.env.test.example` template (credentials not committed)
- `docs/e2e-testing.md` comprehensive guide

### 6. Validation (30 min)

**Actions:**

- Create `.env.test` with actual credentials (not committed)
- Ensure ngrok tunnels are running
- Run `npm run test:e2e`
- Verify:
  - Database backup created
  - Test executes successfully
  - Screenshots generated in `docs_screens/`
  - Database restored to original state
- Test failure scenario:
  - Intentionally break test
  - Verify database still restored
- Clean up test data if any leaked

**Deliverables:**

- Fully working E2E test suite
- Verified database safety mechanism
- Screenshots available for documentation

## Key Adjustments from Original ChatGPT Plan

### What We Changed:

- ✅ **Route correction**: Uses `/kanban` instead of `/dashboard` (actual default landing page)
- ✅ **Database safety**: Added backup/restore mechanism to prevent data pollution
- ✅ **Environment variables**: Credentials and config externalized, not hardcoded
- ✅ **Bearer token auth**: Handled localStorage token persistence
- ✅ **Screenshots in .gitignore**: Generated locally, not committed to repo
- ✅ **Playwright over Puppeteer**: Using industry-standard E2E framework
- ✅ **Selector strategy**: Acknowledged lack of `data-testid` attributes, using semantic selectors

### What We Kept:

- ✅ Overall phase structure (6 phases)
- ✅ Screenshot strategy for documentation
- ✅ npm script approach
- ✅ 4-hour time estimate
- ✅ Single smoke test for MVP

## Actual Codebase Context

### Frontend Stack:

- **Build Tool**: Vite 6.2.4
- **Framework**: Vue 3.5.13 with TypeScript
- **Dev Server**: Port 5173
- **Auth Method**: Bearer token (stored in localStorage)

### Key Routes:

- `/login` - Login page
- `/kanban` - Main dashboard (default after login)
- `/jobs/create` - Job creation form
- `/jobs/:id` - Job detail/edit
- `/timesheets/weekly` - Weekly timesheet (Xero integration)

### API Configuration:

- Configured via `VITE_API_BASE_URL` in `.env`
- Current ngrok URLs:
  - Frontend: `https://msm-workflow-front.ngrok-free.app`
  - Backend: `https://msm-workflow.ngrok-free.app`
- Fallback: `http://localhost:8000`

### Authentication:

- Login form selectors:
  - Username: `#username` (label: "E-mail")
  - Password: `#password` (label: "Password")
  - Submit: button with text "Sign In"
- Token stored as `auth_token` in localStorage
- Auth check endpoint: `/accounts/me/`

### Job Creation Requirements:

- Required fields:
  - Job name (text input)
  - Client selection (lookup/autocomplete)
  - Estimated materials (number)
  - Estimated hours (number)
- Optional fields:
  - Contact (related to client)
  - Description (rich text editor)
  - Various other metadata

## Timeline

**Total Estimated Time**: 4 hours

| Phase | Task                           | Time      |
| ----- | ------------------------------ | --------- |
| 1     | Install & Configure Playwright | 30 min    |
| 2     | Database Safety Wrapper        | 45 min    |
| 3     | Auth Fixture                   | 30 min    |
| 4     | Job Creation Test              | 1.5 hours |
| 5     | Environment & Documentation    | 30 min    |
| 6     | Validation                     | 30 min    |

## Success Criteria

- ✅ Single E2E smoke test passes consistently
- ✅ Test covers: login → job creation → verification
- ✅ 4 screenshots generated to `docs_screens/`
- ✅ Database safely backed up and restored
- ✅ Can run via `npm run test:e2e`
- ✅ Documentation complete and accurate
- ✅ No test data pollution in database

## Future Enhancements (Out of Scope for MVP)

- Additional test scenarios (timesheet entry, payroll sync)
- CI/CD integration (GitHub Actions)
- Parallel test execution
- Visual regression testing
- API contract testing
- Performance benchmarking
- Mobile viewport testing
