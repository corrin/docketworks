# Developer Review & Release Checklist — Inline Delivery Receipt (Current Model, no i18n)

Use this checklist to validate the migration of Delivery Receipts allocation into the inline editor in [src/components/purchasing/PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue:1) with orchestration in [src/views/purchasing/PurchaseOrderFormView.vue](src/views/purchasing/PurchaseOrderFormView.vue:1). This checklist reflects the current model and endpoints and removes any internationalization requirements.

Related plan files:

- [00-executive-summary.md](./00-executive-summary.md)
- [01-questions-for-confirmation.md](./01-questions-for-confirmation.md)
- [02-feature-parity-matrix.md](./02-feature-parity-matrix.md)
- [03-ux-spec-inline-allocation.md](./03-ux-spec-inline-allocation.md)
- [04-architecture-and-data-flow.md](./04-architecture-and-data-flow.md)
- [05-state-management-and-dirty-guards.md](./05-state-management-and-dirty-guards.md)
- [06-api-adapter-and-endpoints.md](./06-api-adapter-and-endpoints.md)
- [07-business-rules-and-edge-cases.md](./07-business-rules-and-edge-cases.md)
- [08-error-handling-optimism-and-reconciliation.md](./08-error-handling-optimism-and-reconciliation.md)
- [09-code-examples-and-focused-snippets.md](./09-code-examples-and-focused-snippets.md)
- [10-rollout-plan-kpis-and-telemetry.md](./10-rollout-plan-kpis-and-telemetry.md)
- [11-task-breakdown-and-acceptance-criteria.md](./11-task-breakdown-and-acceptance-criteria.md)

---

## A. Architecture & Separation of Concerns

- [ ] No backend logic implemented in frontend components or stores.
- [ ] All API entity types sourced exclusively from [src/api/generated/api.ts](src/api/generated/api.ts:1).
- [ ] UI-only types (e.g., inline editor rows) are local to components and not used to represent persisted data.
- [ ] [PurchaseOrderFormView.vue](src/views/purchasing/PurchaseOrderFormView.vue:1) orchestrates fetching jobs, existing allocations, and posting single-line receipts.
- [ ] [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue:1) is presentational; no API calls inside it.
- [ ] Allocation inline editor is a UI-only component (new [AllocationCellEditor.vue](src/components/purchasing/AllocationCellEditor.vue)).

## B. Receipt Lifecycle & Store Reuse

- [ ] Reuses [src/stores/deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts:1) for:
  - fetchPurchaseOrder
  - fetchJobs (stock-holding job included)
  - fetchExistingAllocations
  - submitDeliveryReceipt (POST a DeliveryReceiptRequest)
- [ ] No new stores introduced.
- [ ] Inline editor posts a single-line map per autosave (partial DeliveryReceiptRequest).

## C. Inline Editor UX

- [ ] “Receipt” column added in [PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue:1) with an inline popover editor per row.
- [ ] Editor fields:
  - Target: Job or Stock (Stock maps to stock-holding job id)
  - Quantity: number, ≥ 0
  - Retail rate (%) for job (UI-only; not sent today) with on-screen hint
  - Stock location (UI-only; not sent today) with on-screen hint
- [ ] Quick actions: Allocate remaining / Allocate all.
- [ ] Autosave on blur/close with debounce (150–300ms); no explicit “Save” button.

## D. Validation & Business Rules

- [ ] Remaining calculation matches legacy:
  - remaining = max(0, line.quantity − (line.received_quantity || 0)) − sum(existing saved allocations for the line)
- [ ] Over-receipt blocked inline. Error: “Exceeds remaining”.
- [ ] Non-negative quantities enforced. Error: “Quantity must be greater than or equal to 0”.
- [ ] Zero-quantity rows are removed before posting.
- [ ] If Target is Stock, map to stock-holding job id before building payload.

## E. Error Handling & Concurrency

- [ ] Last-writer-wins policy maintained.
- [ ] On POST success: refresh Purchase Order detail and Existing Allocations.
- [ ] On POST failure: show inline error and toast; keep editor open, preserve user inputs for retry.
- [ ] DEV-only logs for POST attempts/outcomes; avoid logging free-text notes.

## F. Accessibility

- [ ] Popover uses role="dialog" with proper labels.
- [ ] Esc closes and returns focus to the trigger.
- [ ] Inline errors are visible and announced via aria-live where applicable.
- [ ] Keyboard path: Enter/Space opens, Alt+R allocate remaining, Alt+A allocate all, Tab/Shift+Tab and arrow navigation are functional.

## G. Performance

- [ ] Inline interactions feel instant (< 100ms perceived).
- [ ] Single-line POST payloads; debounce autosave to reduce call frequency.
- [ ] Small POs: no pagination required in this flow.

## H. Testing

- [ ] Unit/integration checks for:
  - Remaining computation parity with legacy
  - Over-receipt block
  - Single-line POST on autosave
- [ ] E2E flow:
  - Edit two lines inline, autosave on blur/close, then verify PO received quantities and previous allocations updated.

## I. Telemetry (Optional)

- [ ] Counters for editor open, quick actions used, autosave outcomes (success/error).
- [ ] Timing from editor open to autosave success.
- [ ] Adoption metric vs. legacy route if both are temporarily visible.

## J. Documentation

- [ ] Short user-facing note or section in release notes explaining:
  - Inline Receipt now available in the PO lines
  - Autosave behavior
  - Quick actions
  - Temporary link to legacy page (if present during overlap)
- [ ] Code comments in the new inline editor clarifying UI-only fields (retail rate, stock location).

## K. Backward Compatibility

- [ ] No new endpoints added.
- [ ] No feature flags required.
- [ ] Retail rate and stock location remain UI-only until schemas are extended.
- [ ] Legacy view can be temporarily linked for verification and then removed cleanly.

---

## Sign-off

- [ ] Product/UX review (layout, quick actions, parity with legacy).
- [ ] Engineering review (store reuse, single-line POST, refresh logic).
- [ ] QA sign-off (remaining parity, over-receipt block, autosave outcomes).
- [ ] Release notes prepared; decommission legacy route after overlap period.
