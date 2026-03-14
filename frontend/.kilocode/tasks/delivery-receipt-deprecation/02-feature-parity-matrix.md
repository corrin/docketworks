# Feature Parity Matrix — Inline Delivery Receipt (Refactored to Current Model)

This matrix maps the current Delivery Receipt flow to the proposed inline model, aligned with the actual implementation and API types found in:

- [src/views/purchasing/DeliveryReceiptFormView.vue](src/views/purchasing/DeliveryReceiptFormView.vue)
- [src/components/purchasing/DeliveryReceiptLinesTable.vue](src/components/purchasing/DeliveryReceiptLinesTable.vue)
- [src/stores/deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts)
- [src/utils/delivery-receipt.ts](src/utils/delivery-receipt.ts)
- [src/api/generated/api.ts](src/api/generated/api.ts)

---

## Legend

- Maintained: Behavior preserved as‑is
- Improved: Same behavior with faster/clearer inline UX
- Needs Decision: Requires a small confirmation (see [01-questions-for-confirmation.md](./01-questions-for-confirmation.md))

---

## Receipt Lifecycle and Data

- Delivery receipt submission

  - Current: Compose allocations per line in a dedicated page, then POST a DeliveryReceiptRequest (record of line_id → DeliveryReceiptLine)
  - Inline: Per‑line inline editor posts a partial DeliveryReceiptRequest containing only the edited line
  - Status: Improved (no navigation, smaller payloads)

- Existing allocations (historical)

  - Current: GET purchasing_rest_purchase_orders_allocations_retrieve, shown as “Previous Allocations”
  - Inline: Same API; a collapsible block inside the cell
  - Status: Maintained

- Jobs list (including stock‑holding)
  - Current: GET purchasing_rest_all_jobs_retrieve; stock‑holding job is special
  - Inline: Same; editor target field offers jobs and Stock. Use Job cell inside PoLinesTable to fulfill this. If the PO line is defined to use the stock holding job, consider this when allocating. If the PO line is defined to use another job, consider this as well. Allow overrides/splits to stock or other jobs, but default behaviour is to consider per default the selected job of the line.
  - Status: Maintained

---

## Per‑Line Allocation Editing

- Add allocation rows

  - Current: “Add” button opens modal; choose Job (or Stock, and MUST BE PREPOPULATED), enter quantity; optional retail_rate or stock_location (UI only today)
  - Inline: “Add” button inside popover; same fields, keyboard‑first
  - Status: Improved

- Update allocation rows

  - Current: Edit in modal; validation prevents invalid quantities
  - Inline: Edit in popover; inline error; focus management
  - Status: Improved

- Delete allocation rows

  - Current: Delete buttons per row
  - Inline: Same
  - Status: Maintained

- Job vs Stock allocation

  - Current: job_id null → replaced with stock‑holding job id before sending
  - Inline: Same mapping; if Stock selected, ensure job_id is the stock‑holding id when building the payload
  - Status: Maintained

- Retail rate (UI‑only)

  - Current: Entered for job allocations; not included in DeliveryReceiptRequest schema
  - Inline: Keep visible; schema will be refactored later (per answers)
  - Status: Maintained

- Stock location (UI‑only)
  - Current: Free text when allocating to stock; not included in request schema
  - Inline: Keep visible; schema will be refactored later (per answers)
  - Status: Maintained

---

## Quantities and Validation

- Remaining calculation

  - Current: remaining = max(0, line.quantity − (line.received_quantity || 0)) − sum(existing saved allocations for that line)
  - Inline: Same formula; current (unsaved) inline entries do not reduce remaining until posted
  - Status: Maintained

- Over‑receipt

  - Current: Disallowed; UI shows warning and prevents save
  - Inline: Same (hard block)
  - Status: Maintained

- Non‑negative quantities

  - Current: Enforced
  - Inline: Same; inline error per field
  - Status: Maintained

- Autosave
  - Current: Explicit save on the standalone view
  - Inline: Autosave integrated with existing PoLinesTable/PurchaseOrderFormView patterns (no save button)
  - Status: Improved

---

## Quick Actions (Right‑sized)

- Allocate remaining

  - Current: Achieved manually
  - Inline: One‑click “Allocate remaining” that fills a single row (Stock by default or current selection)
  - Status: Improved

- Allocate all
  - Current: Manual
  - Inline: One‑click “Allocate all” (respecting remaining)
  - Status: Improved

---

## Accessibility

- Keyboard navigation

  - Current: Basic modal focus behavior
  - Inline: Popover with focus trap, Esc to close, Tab/Shift+Tab; quick action shortcuts optional
  - Status: Improved

- ARIA
  - Current: Standard patterns
  - Inline: Popover uses role="dialog"; field errors announced via aria‑live="polite"
  - Status: Improved

---

## Performance

- Payload size

  - Current: One POST for all edited lines at once
  - Inline: One POST per line when the user changes that line (partial record), typically smaller payload
  - Status: Improved UX (less waiting); similar total network cost for small POs

- Perceived latency
  - Current: Modal‑based; save involves full screen context
  - Inline: Optimistic update; simple POST and refresh on success
  - Status: Improved

---

## Summary of Parity

- Maintained:

  - Core allocation semantics (job/stock, per‑line multi‑rows, over‑receipt block, remaining formula, last‑writer‑wins)
  - Display of previous (saved) allocations
  - Jobs list with stock‑holding

- Improved:

  - Inline editing UX (no navigation), quick actions (allocate remaining/all), inline errors and keyboard handling, perceived latency

- Confirmed Decisions:
  - Keep retail_rate and stock_location fields in the UI (not persisted today)
  - Autosave integrated; no explicit Save button

---

## Related References

- [00-executive-summary.md](./00-executive-summary.md)
- [01-questions-for-confirmation.md](./01-questions-for-confirmation.md)
- [03-ux-spec-inline-allocation.md](./03-ux-spec-inline-allocation.md)
- [04-architecture-and-data-flow.md](./04-architecture-and-data-flow.md)
