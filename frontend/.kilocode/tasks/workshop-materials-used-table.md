# Workshop Job View: "Materials Used" Table Plan

## Goal

Add a lightweight, tablet-friendly "Materials used" table to the bottom of `src/views/WorkshopJobView.vue` that lets workshop staff record and adjust material usage against a job’s **Actual** cost set.

This is intentionally narrower than the office "Actual Costs" tab: workshop staff should focus on **material lines** only.

---

## Requirements

### Functional

1. **Show a "Materials used" table** at the end of the workshop job page.
2. Table columns:
   - **Item**: uses `src/views/purchasing/ItemSelect.vue`.
   - **Description**: editable for eligible lines (autosave).
   - **Quantity**: editable for eligible lines (autosave); default `1` for new entries.
   - **Actions**: trash icon deletes the line.
3. **Show all actual material lines**
   - Display all lines from the job’s `actual` cost set where `kind === 'material'`, including delivery-receipt sourced lines.
4. **Create cost line on item selection**
   - When the user selects an item in the **Item** column for a new row, create a new actual material line by **consuming stock**.
5. **Edit existing lines**
   - Allow editing **quantity** and **description** for eligible material lines.
   - Persist edits via PATCH (`job_rest_cost_lines_partial_update`) using the same debounced optimistic + rollback pattern as `SmartCostLinesTable.vue`.
6. **Delete line**
   - Clicking the trash icon deletes the cost line (backend + UI).

### Non-functional

1. **Use shadcn-vue components** where possible (`Card`, `Table`, `Button`, etc).
2. **Tablet-first UX**
   - Large touch targets, clear spacing, and obvious feedback for saving/failed saves.
3. **Safe concurrency behavior**
   - If creation/edit/deletion fails, show an error toast and keep UI consistent (rollback optimistic changes).

---

## Data Sources & API Integration

### Load existing lines

Preferred: fetch the actual cost set directly:

- `GET /job/rest/jobs/:id/cost_sets/actual/` (`fetchCostSet(jobId, 'actual')`)
- Filter `cost_lines` to `kind === 'material'`.

This keeps the table fresh without reloading the full job payload.

### Create line (stock consumption)

Use the same mechanism as the office actual tab:

- `POST /purchasing/rest/stock/:id/consume/` (`useStockStore().consumeStock`)
- Returns `StockConsumeResponse` which includes the created `line`.

Notes:

- `ItemSelect.vue` emits `update:unit_cost`, but not unit revenue.
- `StockItem` includes `unit_revenue`; if present, we can pass it as `unit_rev`, otherwise derive it (e.g. via company markup, as `SmartCostLinesTable.vue` does).

### Edit line (quantity/description)

- `PATCH /job/rest/cost_lines/:cost_line_id/` (`costlineService.updateCostLine`)
- Payload: `PatchedCostLineCreateUpdateRequest`, e.g. `{ quantity: 2 }`, `{ desc: '...' }`.
- Backend updates inventory automatically for stock-consumed lines when quantity changes; the client only PATCHes the cost line.

Autosave behavior should match `src/components/shared/SmartCostLinesTable.vue`:

- debounced save (~600ms),
- optimistic apply,
- rollback on error.

### Delete line

- `DELETE /job/rest/cost_lines/:cost_line_id/delete/` (`costlineService.deleteCostLine`)

---

## Editing Rules (match existing patterns)

Use the same eligibility rules as the office grid to avoid surprises:

- **Delivery receipt material lines** (`meta.source === 'delivery_receipt'`) are **read-only** (no edits, no item changes).
- **Stock-consumed material lines** allow editing **quantity** and **description**.
- **Item** changes:
  - allowed for the draft row only;
  - disabled for existing stock-consumed lines (to avoid changing the stock linkage).

---

## UX Behavior (Proposed)

### Table layout

- Shadcn `Card` containing a `Table`.
- Rows:
  - existing actual material lines,
  - one always-present draft row at the bottom for "add new material".

### Draft row flow

1. Draft row starts with:
   - `ItemSelect` empty,
   - `Quantity` default `1`,
   - `Description` empty/placeholder.
2. On selecting an item:
   - show "creating…" state for that row,
   - call `consumeStock(stockId, payload)`,
   - on success: append `response.line` and reset the draft row,
   - on failure: toast error; keep draft row to retry.

### Edit flow

- Inline edit Quantity/Description.
- Save on blur + debounced scheduling.
- Show small per-row saving indicator (optional nice-to-have).

### Delete flow

- Tap trash icon.
- Confirm delete.
- Disable button while request is in-flight.

---

## Architecture

### Component structure

Create a new focused component:

- `src/components/workshop/WorkshopMaterialsUsedTable.vue`

Responsibilities:

- Load and hold `materialLines: CostLine[]`.
- Provide draft-row state for new material consumption.
- Provide inline editing with autosave:
  - reuse `useCostLineAutosave` + `costlineService.updateCostLine`.
- Provide delete behavior:
  - call `costlineService.deleteCostLine` and remove row locally.

Integration:

- Render component at the end of `src/views/WorkshopJobView.vue`.
- Pass `jobId` as prop.

---

## Task Breakdown

1. Create `WorkshopMaterialsUsedTable.vue` skeleton (Card + Table + empty states).
2. Load actual cost set and filter `kind === 'material'`.
3. Implement draft row with `ItemSelect` + quantity/description display.
4. Create on item selection via `stockStore.consumeStock`, append returned `line`.
5. Implement inline editing (quantity + description) using `useCostLineAutosave` + `costlineService.updateCostLine`.
6. Implement delete action via `costlineService.deleteCostLine`.
7. Integrate into `WorkshopJobView.vue`.
8. Run `npm run type-check` and fix any issues.

---

## Out of Scope (for this iteration)

- Totals/summary calculations and reporting.
- Bulk entry / barcode scanning workflows.
- Reordering lines.
- Editing unit cost/unit revenue.
