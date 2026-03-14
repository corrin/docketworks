# E2E Test Failures Triage

**Date:** 2025-12-11
**Branch:** fix/e2e-test-failures
**Test Run Results:** 5 failed, 17 did not run, 10 passed

---

## Issue #1: Company Defaults UI Test

**Test:** `company-defaults.spec.ts:42` - "test company defaults via app store"

**Error:**

```
TimeoutError: page.waitForSelector: Timeout 15000ms exceeded.
waiting for locator('text=General') to be visible
```

**Root Cause:** Test expects a "General" text/card element that no longer exists in the current Company Defaults page UI.

**Classification:** Test update needed

**Severity:** Low

**Fix Required:** Update test selectors to match current Company Defaults page structure.

**Files to investigate:**

- `tests/company-defaults.spec.ts`
- The Company Defaults view component

---

## Issue #2: Client Search Dropdown Not Appearing

**Affected Tests:**

- `create-estimate-entry.spec.ts:119` - "add Labour entry" (beforeAll failure)
- `create-job.spec.ts:44` - "create T&M with first contact"
- `create-timesheet-entry.spec.ts:72` - "verify initial Time & Expenses is zero" (beforeAll failure)

**Error:**

```
TimeoutError: locator.waitFor: Timeout 10000ms exceeded.
waiting for locator('[data-automation-id="client-search-results"]') to be visible
```

**Root Cause:** When typing "ABC" in the client search input on the Create Job page, the search results dropdown (`client-search-results`) doesn't appear within 10 seconds.

**Classification:** Needs investigation - could be:

1. Race condition / timing issue in tests
2. App regression - client search API not returning results
3. UI change - dropdown rendered differently

**Severity:** High - blocks 3+ test suites

**Screenshot context:** Page shows Create Job form with "ABC" typed in client search input but no dropdown visible.

**Files to investigate:**

- `src/components/job/ClientSearch.vue` (or similar)
- Client search API service
- `tests/fixtures/helpers.ts:60` (where the wait happens)

---

## Issue #3: Contact Form Stuck in "Saving..." State

**Affected Tests:**

- `edit-job-settings.spec.ts:23` - "create a job to edit" (in first run)
- `create-timesheet-entry.spec.ts` beforeAll (in first run)

**Error:**

```
expect(locator).toHaveText("Create Contact") failed
Expected: "Create Contact"
Received: "Saving..."
```

**Root Cause:** The contact form submit button in `ContactSelectionModal.vue` is stuck showing "Saving..." indefinitely. The `isLoading` prop never resets to `false`.

**Classification:** Potential app bug OR test timing issue

**Severity:** High - blocks job creation when no existing contacts

**Screenshot context:** Contact selection modal shows "Loading contacts..." and submit button stuck on "Saving..."

**Code reference:** `src/components/ContactSelectionModal.vue:298-300`

```vue
{{ isLoading ? 'Saving...' : isEditing ? 'Update Contact' : 'Create Contact' }}
```

**Files to investigate:**

- `src/components/ContactSelectionModal.vue`
- `src/composables/useContactManagement.ts`
- Contact API service

**Note:** This appeared in first test run but not consistently in second run. May be intermittent or dependent on database state.

---

## Issue #4: Internal Notes Test Failure

**Test:** `edit-job-settings.spec.ts:314` - "change internal notes"

**Error:**

```
expect(locator).toContainText(expected) failed
```

**Root Cause:** TBD - appeared in second test run

**Classification:** Needs investigation

**Severity:** Medium

**Files to investigate:**

- `tests/job/edit-job-settings.spec.ts:314`
- Internal notes component/field

---

## Summary Table

| #   | Issue                                | Tests Affected | Classification      | Severity |
| --- | ------------------------------------ | -------------- | ------------------- | -------- |
| 1   | Company Defaults UI changed          | 1              | Test update         | Low      |
| 2   | Client search dropdown not appearing | 3+             | Needs investigation | High     |
| 3   | Contact form stuck in Saving state   | 2+             | Potential app bug   | High     |
| 4   | Internal notes test failure          | 1              | Needs investigation | Medium   |

---

## Next Steps

1. [ ] Investigate Issue #2 (client search) - check if app bug or test timing
2. [ ] Investigate Issue #3 (contact saving) - check contact API/composable
3. [ ] Update Issue #1 (company defaults) - simple selector fix
4. [ ] Investigate Issue #4 (internal notes) - need more details

---

## Test Environment Notes

- Tests run with 4 workers in parallel
- Database is backed up and restored between test runs
- Some tests depend on `beforeAll` fixtures that create shared test data
