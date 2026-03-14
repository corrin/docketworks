# Data Automation ID Naming Convention

This document defines the naming convention for `data-automation-id` attributes.

## Purpose

`data-automation-id` attributes provide stable identifiers for UI elements that can be targeted programmatically (E2E tests, scripts, automation tools). Unlike CSS classes or text content, these IDs are:

- Immune to styling changes
- Self-documenting (the component name tells you which file to look in)
- Globally unique across the application

## Naming Convention

### Format

```
[ComponentName]-[identifier]
```

### Components

1. **ComponentName** (required): The exact Vue component name (PascalCase)

   - Must match the component's filename (e.g., `AdminCompanyView.vue` → `AdminCompanyView`)
   - This makes it trivial to find the source file

2. **identifier** (required): Descriptive name for the element
   - Use kebab-case
   - Be descriptive but concise
   - For dynamic items, append the unique ID: `ContactCard-{id}`
   - For mobile-specific elements, append `-mobile`: `AppNavbar-create-job-mobile`

### Examples

```html
<!-- AdminCompanyView.vue -->
<button data-automation-id="AdminCompanyView-general-button">General</button>
<button data-automation-id="AdminCompanyView-save-button">Save All</button>

<!-- SectionModal.vue -->
<div data-automation-id="SectionModal-content">...</div>

<!-- ClientSearch.vue -->
<input data-automation-id="ClientSearch-input" />
<div data-automation-id="ClientSearch-results">...</div>

<!-- ContactSelectionModal.vue -->
<button data-automation-id="ContactSelectionModal-submit">Create Contact</button>
<div data-automation-id="ContactSelectionModal-card-abc123">...</div>

<!-- AppNavbar.vue - responsive elements -->
<router-link data-automation-id="AppNavbar-create-job">Create Job</router-link>
<!-- desktop -->
<router-link data-automation-id="AppNavbar-create-job-mobile">Create Job</router-link>
<!-- mobile -->
```

## Rules

1. **Global Uniqueness**: Every `data-automation-id` must be unique across the entire application (except for dynamic IDs with different suffixes).

2. **Component Name Must Match**: The prefix must exactly match the Vue component filename.

3. **Tests Must Use IDs**: E2E tests should reference elements by `data-automation-id`:
   ```typescript
   await page.locator('[data-automation-id="ClientSearch-input"]').fill('ABC')
   await page.locator('[data-automation-id="AdminCompanyView-save-button"]').click()
   ```

## Finding Elements

When you see an automation ID in a test:

1. Take the prefix before the first hyphen (e.g., `AdminCompanyView`)
2. Search for `AdminCompanyView.vue`
3. The element is in that file

This convention eliminates guesswork about where elements are defined.
