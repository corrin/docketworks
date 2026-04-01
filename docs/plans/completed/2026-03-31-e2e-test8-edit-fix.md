# Fix E2E test 8: "edit quantity and unit cost" — autosave PATCH never fires

## Context

Test 8 in `create-estimate-entry.spec.ts` fails because `dblclick()` + `keyboard.type()` on `<input type="number">` doesn't reliably select/replace text in headless Chromium. The typed value goes nowhere, no dirty state is set, no autosave fires, and `waitForAutosave` times out.

Every other test in the same file that edits input values uses `click()` + `fill()` — which works because Playwright's `fill()` clears the input first then types the new value. The edit test is the only one using the broken `dblclick()` + `keyboard.type()` pattern.

## Fix

**File:** `frontend/tests/job/create-estimate-entry.spec.ts` (lines 220-230)

Replace:
```typescript
const qtyInput = autoId(page, `SmartCostLinesTable-quantity-${rowIndex}`)
await qtyInput.dblclick()
await page.keyboard.type('3')
await page.keyboard.press('Tab')

const unitCostInput = autoId(page, `SmartCostLinesTable-unit-cost-${rowIndex}`)
await unitCostInput.dblclick()
await page.keyboard.type('25')
await page.keyboard.press('Tab')
```

With:
```typescript
const qtyInput = autoId(page, `SmartCostLinesTable-quantity-${rowIndex}`)
await qtyInput.click()
await qtyInput.fill('3')
await page.keyboard.press('Tab')

const unitCostInput = autoId(page, `SmartCostLinesTable-unit-cost-${rowIndex}`)
await unitCostInput.click()
await unitCostInput.fill('25')
await page.keyboard.press('Tab')
```

This matches the pattern used by the labour test (line 136-138), material test (line 171-173), and unit revenue test (line 255-256) — all of which pass.

## Verification

Run E2E test 8 on UAT:
```bash
cd frontend && npx playwright test tests/job/create-estimate-entry.spec.ts --grep "edit quantity and unit cost"
```
