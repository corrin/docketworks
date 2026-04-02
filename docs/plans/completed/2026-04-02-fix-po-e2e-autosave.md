# Fix: PO line save not firing in E2E test

## Context

E2E test `add a line item to the purchase order` times out waiting for a PATCH. Two issues:

### Issue 1: PostgreSQL FOR UPDATE incompatibility (already fixed)

`select_for_update()` + `select_related("supplier")` on nullable FK fails in PostgreSQL. Fixed with `select_for_update(of=("self",))` in `purchasing_rest_service.py:414` and `delivery_receipt_service.py:50`.

### Issue 2: Autosave fires before line is complete

The save flow: each field `fill()` → `update:lines` → deep watcher → 500ms debounce → `saveLines()`. The test fills description, waits 300ms, fills quantity, waits 300ms, fills unit_cost. The watcher's 500ms debounce can fire after the description or quantity fill — before unit_cost is set. When `saveLines()` runs:

1. `isValidLine()` requires content + price (unit_cost > 0 or price_tbc)
2. Line has description but unit_cost is still `null`
3. `incompleteLines` filter catches it → "missing price" toast.error() → **early return, no PATCH**

The debounce timer resets on each field change, but the 300ms `waitForTimeout` between fills means the timer can fire between fills.

## Fix

**File:** `frontend/tests/purchasing/create-purchase-order.spec.ts`

Remove the `waitForTimeout(300)` pauses between fills. Fill all three fields rapidly so the debounce timer only fires once, after all fields are set. Set up the autosave listener before filling to avoid race conditions.

```typescript
// Fill in line details — fill all fields rapidly so the 500ms
// autosave debounce only fires once, after all values are set
await descriptionInput.fill('[TEST] Material Item')
await qtyInput.fill('5')
const autosavePromise = waitForPoAutosave(page)
await costInput.click()
await costInput.fill('25.50')
await page.keyboard.press('Tab')
await autosavePromise
```

Also remove the `qtyInput.clear()` — `fill()` already clears before typing.

## Files to modify

- `frontend/tests/purchasing/create-purchase-order.spec.ts` — remove delays between fills, set up listener before last fill

## Already fixed (this session)

- `apps/purchasing/services/purchasing_rest_service.py:414` — `select_for_update(of=("self",))`
- `apps/purchasing/services/delivery_receipt_service.py:50` — same

## Verification

`cd frontend && npx playwright test tests/purchasing/create-purchase-order.spec.ts`
