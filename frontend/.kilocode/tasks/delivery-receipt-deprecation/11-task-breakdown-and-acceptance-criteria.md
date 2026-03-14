# Task Breakdown and Acceptance Criteria — Inline Delivery Receipt (Current Model, no i18n)

This breakdown reflects the actual functionality and schemas. No drafts/commit lifecycle, no feature flags, no batch endpoints, no i18n, no lots/serials/bins/UoM.

References:

- [00-executive-summary.md](./00-executive-summary.md)
- [02-feature-parity-matrix.md](./02-feature-parity-matrix.md)
- [03-ux-spec-inline-allocation.md](./03-ux-spec-inline-allocation.md)
- [04-architecture-and-data-flow.md](./04-architecture-and-data-flow.md)
- [05-state-management-and-dirty-guards.md](./05-state-management-and-dirty-guards.md)
- [06-api-adapter-and-endpoints.md](./06-api-adapter-and-endpoints.md)
- [07-business-rules-and-edge-cases.md](./07-business-rules-and-edge-cases.md)
- [08-error-handling-optimism-and-reconciliation.md](./08-error-handling-optimism-and-reconciliation.md)
- [09-code-examples-and-focused-snippets.md](./09-code-examples-and-focused-snippets.md)
- [10-rollout-plan-kpis-and-telemetry.md](./10-rollout-plan-kpis-and-telemetry.md)
- [12-dev-checklist-for-review-and-release.md](./12-dev-checklist-for-review-and-release.md)

---

## T1 — Add “Receipt” column to PoLinesTable

- Files:
  - [src/components/purchasing/PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue:1)
- Work:
  - Add a new column named “Receipt”.
  - Mount child [AllocationCellEditor.vue](src/components/purchasing/AllocationCellEditor.vue) per row.
  - Provide props: jobs, existingAllocations, defaultRetailRate, stockHoldingJobId.
  - Emit `receipt:save` with `{ lineId, editorState }`.
- AC:
  - Column renders for each line.
  - Disabled state respects existing `readOnly`.
  - Emits `receipt:save` on autosave from the editor.

Estimate: 0.5 day

---

## T2 — New AllocationCellEditor component (UI-only)

- Files:
  - [src/components/purchasing/AllocationCellEditor.vue](src/components/purchasing/AllocationCellEditor.vue:1)
- Work:
  - Inline popover editor for “this receipt” allocations per line.
  - Rows: Target (Job or Stock, should be prepopulated from the current PoLine selected job), Quantity; when Job: Retail rate (%) UI-only; when Stock: Stock location UI-only (+ Retail rate as well).
  - Quick actions: Allocate remaining / Allocate all.
  - No explicit Save; autosave on blur/close with debounce (150–300ms).
  - Inline validation: non-negative, no over-receipt (sum ≤ Remaining).
  - Must be edited ONLY after the user changes the PO status to "submitted_to_supplier".
  - Creating allocations MUST change PO status to either "partially received" or "fully received" automatically.
- AC:
  - Editor opens from the “Receipt” cell and updates “This Receipt” and “Remaining” instantly.
  - Over-receipt shows inline error and blocks autosave.
  - Emits `save` with rows when valid; removes zero-quantity rows before emitting.

Estimate: 1 day

---

## T3 — Orchestrate in PurchaseOrderFormView

- Files:
  - [src/views/purchasing/PurchaseOrderFormView.vue](src/views/purchasing/PurchaseOrderFormView.vue:1)
- Work:
  - Fetch jobs (with stock-holding) via deliveryReceiptStore.fetchJobs().
  - Fetch existing allocations via deliveryReceiptStore.fetchExistingAllocations(poId).
  - Pass data to PoLinesTable.
  - Handle `receipt:save`:
    - Convert editor rows → DeliveryReceiptAllocation[] (job_id + quantity; stock target maps to stockHoldingJobId).
    - Build a single-line DeliveryReceiptRequest using [transformDeliveryReceiptForAPI](src/utils/delivery-receipt.ts:22).
    - Call deliveryReceiptStore.submitDeliveryReceipt(poId, request.allocations).
    - On success, refresh PO and existing allocations.
- AC:
  - After autosave, PO received quantities and existing allocations refresh; remaining updates.
  - Failures show toast; inputs preserved in editor for retry.

Estimate: 0.5 day

---

## T4 — Wire remaining calculation (unchanged logic)

- Files:
  - [src/components/purchasing/AllocationCellEditor.vue](src/components/purchasing/AllocationCellEditor.vue:1)
- Work:
  - Compute Remaining as:
    - `remaining = max(0, line.quantity - (line.received_quantity || 0)) - sum(existingSavedAllocationsForLine)`
  - Use existing `existingAllocations` data for saved totals.
- AC:
  - Remaining equals legacy view for the same PO/line state.

Estimate: 0.25 day

---

## T5 — Error handling and toasts

- Files:
  - [src/components/purchasing/AllocationCellEditor.vue](src/components/purchasing/AllocationCellEditor.vue:1)
  - [src/views/purchasing/PurchaseOrderFormView.vue](src/views/purchasing/PurchaseOrderFormView.vue:1)
- Work:
  - Show inline error “Exceeds remaining” when blocking autosave.
  - On POST failure, show “Failed to save receipt. Try again.” and preserve inputs.
  - On success, show “Receipt saved”.
- AC:
  - Inline feedback is clear; last-writer-wins behavior preserved.

Estimate: 0.25 day

---

## T6 — Remove legacy dependency and overlap link (optional)

- Work:
  - Add a temporary link under PO header to open the legacy Delivery Receipt screen for verification (optional).
  - After validation period, remove the link and clean up dead code paths.
- AC:
  - Optional overlap link exists for validation period only.
  - Clean removal after acceptance.

Estimate: 0.25 day

---

## T7 — QA and E2E

- Work:
  - Manual test plan:
    - Allocate remaining to Stock on one line; verify refresh updates Remaining and “Previously Received”.
    - Allocate to a Job on another line with a retail rate (UI-only); verify POST payload excludes retail_rate.
    - Over-receipt attempt shows inline error and blocks autosave.
    - Two quick edits in a row debounce into a single POST.
  - E2E happy path (optional):
    - Two-line autosave then verify persisted totals.
- AC:
  - Manual plan executed with no blockers.
  - Optional E2E passing in CI.

Estimate: 0.5–1 day

---

## Acceptance Criteria Summary

- Inline editor delivers equivalent functionality to the current screen:
  - Allocate to jobs/stock, multiple rows per line.
  - Legacy Remaining calculation preserved.
  - Over-receipt blocked.
- Autosave posts one line at a time and refreshes PO + existing allocations on success.
- No regressions in PO lines autosave already present in the PO form view.
- UI-only fields retained: Retail rate (%) for job and Stock location note (not in POST).

---

## Suggested Order

1. T1 → T2 → T3 → T4 → T5 → T7 → (T6 optional)

Total estimate: ~2.5–3.5 days
