# Estimate Entry Test Bugs

Tracking bugs discovered while building E2E tests for estimate entries.

---

## Bug 1: Labour test - `findRowByDescription` returns null but row exists

**Status:** Investigating

**Test:** `create estimate entries > add Labour entry`

**Symptom:**

- After reload, `findRowByDescription(page, 'Labour')` returns null
- But the page snapshot clearly shows a Labour row with textarea value "Labour"

**Evidence from error context:**

```yaml
- row "Labour LABOUR Labour $64.00 $210.00 02/DEC/25 Delete line":
    - cell "Labour":
        - textbox: Labour # <-- This IS "Labour"
```

**Hypothesis:**

- Timing issue? Page not fully rendered when we search?
- Selector issue? `data-automation-id^="cost-line-row-"` not matching?
- Textarea selector issue? `.locator('textarea').first()` not finding the right element?

**Debug steps:**

1. Add console.log to see how many rows are found
2. Log each textarea value found during iteration
3. Check if the automation-id prefix is correct

---

## Bug 2: Edit test - quantity doesn't save, but unit_cost does

**Status:** Investigating

**Test:** `edit costline values > edit quantity and verify unit cost auto-calculates unit revenue`

**Symptom:**

- After editing quantity to 3 and unit_cost to 25, then reload
- quantity=1 (not saved), unit_cost=25 (saved), unit_rev=30 (auto-calculated)

**Evidence from error context:**

```yaml
- row "Adjustment Select Item Test Adjustment for Editing $25.00 $30.00":
    - spinbutton: '1' # <-- Should be "3"
    - spinbutton: '25' # <-- Correct
    - spinbutton: '30' # <-- Auto-calculated from 25
```

**Hypothesis:**

- Playwright `fill()` might not trigger Vue's `@update:modelValue` properly
- BUT unit_cost uses the same pattern and it worked...
- Maybe the first edited field doesn't trigger autosave?
- Maybe quantity needs blur event but we Tab away too fast?

**Debug steps:**

1. Try `dblclick()` + `type()` instead of `fill()` (more realistic user behavior)
2. Check if order matters - try editing unit_cost first, then quantity
3. Add logging to see what autosave captures

---

## Bug 3: Material change test - two issues

**Status:** Investigating (one fixed, one remaining)

**Test:** `change material code > change material code for a costline`

### Issue 3a: `.item-select-trigger` not found (FIXED)

**Symptom:**

- Test times out looking for `.item-select-trigger` class
- The inactive row renders a plain Button, not ItemSelect

**Fix applied:**

1. Added `data-automation-id` to inactive row's div
2. Click the Button to activate row (now also opens dropdown due to UX improvement)
3. UX improvement: clicking item button now also sets `openItemSelect.value = true`

### Issue 3b: Material change doesn't persist after reload (APP BUG FOUND)

**Symptom:**

- Test successfully selects M10 item from dropdown
- Console shows: "Selecting new item: M10 X 30 ZINC CL 4.6 HEX BOLT"
- After reload, row still shows M8 ZINC WING NUT

**Root cause identified:**
When changing an item on an EXISTING line, the code:

1. Updates `desc` and `unit_cost` from the new stock item (lines 558-559)
2. Saves those fields to backend (lines 592-601)
3. BUT does NOT update `ext_refs.stock_id` to reference the new item

The save patch only includes:

```typescript
const patch: PatchedCostLineCreateUpdate = {
  desc: line.desc || '',
  unit_cost: Number(line.unit_cost ?? 0),
  unit_rev: Number(line.unit_rev ?? 0),
}
// Missing: ext_refs: { stock_id: val }
```

**Fix needed:**
When selecting a new item for an existing line, also update and save `ext_refs.stock_id`:

```typescript
// After updating desc and unit_cost, also update ext_refs
Object.assign(line, {
  ext_refs: { ...(line.ext_refs || {}), stock_id: val },
})

// And include in the save patch
const patch: PatchedCostLineCreateUpdate = {
  desc: line.desc || '',
  unit_cost: Number(line.unit_cost ?? 0),
  unit_rev: Number(line.unit_rev ?? 0),
  ext_refs: { stock_id: val }, // <-- Add this
}
```

---

## Notes

- All tests use `test.describe.serial` so they share state within a suite
- Each suite creates its own job to avoid cross-test interference
- Helper functions: `findRowByDescription`, `findRowIndexByDescription`, `navigateToEstimateTab`, `createTestJob`, `addAdjustmentEntry`
