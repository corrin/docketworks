# Data Automation ID Naming Convention

This document defines the naming convention for `data-automation-id` attributes —
the stable selector contract the E2E suite depends on.

## Purpose

`data-automation-id` attributes provide stable identifiers for UI elements that can
be targeted programmatically (E2E tests, scripts, automation tools). Unlike CSS
classes or text content, these IDs are:

- Immune to styling changes
- Immune to refactors (see "prefixes are frozen" below)
- Globally unique across the application

`data-automation-id` is the only test-hook attribute in this codebase. `data-testid`
(Playwright's default) is not used anywhere in `src/` or `tests/` — do not introduce
it; a second attribute for the same concept is a sibling implementation.

## Naming Convention

### Format

```
[Prefix]-[identifier]
```

### Components

1. **Prefix** (required): a PascalCase component name.
   - For a **new** id, use the React component that renders the element
     (`PoSummaryCard.tsx` → `PoSummaryCard-reference`).
   - **Existing prefixes are frozen wire contract, not filenames.** The suite's
     specs were ported holding the original ids, so several prefixes name the
     component the element belonged to before the React rewrite and do not match
     the current file: `JobCreatePage.tsx` renders `JobCreateView-*`,
     `CompaniesListPage.tsx` renders `CompaniesTable-*`. Never rename a prefix to
     match a file — that silently breaks every spec that holds it and buys nothing.
   - Shared components that render on behalf of a caller take an `automationId` /
     `automationIdPrefix` prop and interpolate it, so the rendered id names the
     owning feature, not the shared widget (`DataTable` renders
     `CompaniesTable-header-name` when `CompaniesListPage` passes the prefix).

2. **identifier** (required): descriptive name for the element.
   - Use kebab-case
   - Be descriptive but concise
   - For dynamic items, append the unique ID via template interpolation:
     `` data-automation-id={`CompaniesTable-row-${company.id}`} ``
   - For mobile-specific duplicates of a desktop element, append `-mobile`:
     `AppNavbar-create-job-mobile`

### Examples (all live in `src/features/`)

```tsx
// shell/AppNavbar.tsx
<Link data-automation-id="AppNavbar-create-job">Create Job</Link>
<button data-automation-id="AppNavbar-logout">Log out</button>

// shared/company/CompanyLookup.tsx
<input data-automation-id="CompanyLookup-input" />
<div data-automation-id="CompanyLookup-results">…</div>
<div data-automation-id={`CompanyLookup-option-${company.id}`}>…</div>

// crm/CompaniesListPage.tsx — frozen v1 prefix, dynamic row and cell ids
<tr data-automation-id={`CompaniesTable-row-${company.id}`}>
  <td data-automation-id={`CompaniesTable-cell-${company.id}-total-spend`}>…</td>
</tr>

// job/JobCreatePage.tsx — frozen v1 prefix
<input data-automation-id="JobCreateView-name-input" />
<button data-automation-id="JobCreateView-submit">Create</button>
```

## Rules

1. **Global Uniqueness**: Every `data-automation-id` must be unique across the
   entire application (except for dynamic ids with different suffixes).

2. **Prefixes are stable**: never renamed, even when components move or are
   renamed. New ids take the current component's name.

3. **Tests target ids through the shared helper**: E2E specs use `autoId` from
   `tests/e2e/helpers.ts` rather than hand-writing the attribute selector:

   ```typescript
   import { autoId } from '../helpers'

   await autoId(page, 'CompanyLookup-input').fill('ABC')
   await autoId(page, 'JobCreateView-submit').click()
   ```

   `autoId(page, id)` is exactly `` page.locator(`[data-automation-id="${id}"]`) ``.
   Semantic locators (`getByRole`, `getByText`) remain fine for elements whose
   accessible role or text is itself the contract (headings, toasts, native
   dialogs); use `data-automation-id` wherever the element is app-specific.

## Finding Elements

When you see an automation id in a test, the prefix is not guaranteed to be a
filename (see "frozen" above), so search by the id itself:

```
grep -r 'JobCreateView-' src/
```

The one file that renders that prefix is the element's home.
