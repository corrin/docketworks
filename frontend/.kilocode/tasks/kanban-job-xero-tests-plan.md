# Test Plan - Kanban + Job (Xero/Attachments/Header)

## Goals

- Cover core Kanban flows on desktop and mobile (status change, assign/flag, search).
- Cover creating Invoice and Quote in Xero from the Job Quote and Actual tabs.
- Cover editing job data via the header and managing attachments.

## Scope

- New Playwright specs under `tests/kanban/` and `tests/job/`.
- Reuse existing fixtures in `tests/fixtures` (auth/helpers).
- Focus on critical end-to-end flows with UI validation and API waits.

## Test Matrix (high level)

### Kanban (desktop)

- Change status (drag and drop or card/status drawer action).
- Assign staff on the card (or panel, per UI).
- Search in Kanban (text filter and result validation).

### Kanban (mobile)

- Change status via drawer (no drag and drop).
- Assign staff via mobile flow.
- Search in Kanban (responsive UI or overlay).

### Job - Quote/Actual (Xero)

- Create a Quote in Xero from the Quote tab.
- Create an Invoice in Xero from the Actual tab.
- Validate success feedback and persisted status/links.

### Job - Header

- Update header fields (name, status, priority, or client, per UI).
- Validate persistence and Kanban reflection where applicable.

### Job - Attachments

- Upload an attachment and validate it appears.
- Remove an attachment and validate state.

## Approach

1. Review existing Playwright specs and fixtures for patterns (login, job creation, navigation helpers).
2. Define test data:
   - Base job reused across Kanban and Job specs.
   - Xero dependencies (tenant/config) and minimal data for Quote/Invoice creation.
   - Small local fixture file for attachment upload.
3. Implement specs by module:
   - `tests/kanban/kanban-desktop.spec.ts`
   - `tests/kanban/kanban-mobile.spec.ts`
   - `tests/job/job-xero-quote-invoice.spec.ts`
   - `tests/job/job-header-attachments.spec.ts`
4. Standardize selectors (data-testid/role/text) and waits via API responses.
5. Validate stability (avoid flake with network waits and selective reloads).

## Risks / Dependencies

- Xero flows require valid tenant/config; align with test environment.
- Kanban actions may depend on drag and drop; mobile needs alternate flows.
- Attachments depend on backend/storage; define local fixture and cleanup.

## Next Steps

- Confirm exact selectors and flows in Kanban and Job Quote/Actual tabs.
- Define standard test jobs and users.
- Implement specs in priority order: Kanban desktop -> Kanban mobile -> Job Xero -> Header/Attachments.
