# UX Spec — Inline Delivery Receipt (Aligned to Current Functionality, no i18n)

This spec defines the inline receipt allocation UX that replaces the standalone Delivery Receipt screen while preserving the same data model and API usage found in:

- [`DeliveryReceiptFormView.vue`](src/views/purchasing/DeliveryReceiptFormView.vue:1)
- [`DeliveryReceiptLinesTable.vue`](src/components/purchasing/DeliveryReceiptLinesTable.vue:1)
- [`deliveryReceiptStore.ts`](src/stores/deliveryReceiptStore.ts:1)
- [`delivery-receipt.ts`](src/utils/delivery-receipt.ts:1)
- [`api.ts`](src/api/generated/api.ts:1555)

---

## Goals and KPIs

- ≤ 3 actions to fully allocate a typical line (Open editor → Allocate remaining → Close).
- < 100ms perceived latency for typing and quick actions via optimistic inline state.
- No navigation away from the PO context.

---

## Inline Entry Point and Summary

- New column “Receipt” in [`PoLinesTable.vue`](src/components/purchasing/PoLinesTable.vue:1).
- Cell content:
  - Summary chip: “This Receipt: X” and “Remaining: Y”
  - Remaining uses the current formula:
    - remaining = max(0, line.quantity − (line.received_quantity || 0)) − sum(existing saved allocations for the line)
  - If “This Receipt” total is 0 (no current rows), show a “+ Add” outline button.

Clicking the cell/trigger opens an anchored popover (or an expandable inline row on mobile).

---

## Popover Editor Contents

- Allocations list (this receipt, unsaved editor state):

  - Rows: Target (Job or Stock), Quantity
  - If Target is a job: Retail rate (%) input (UI‑only; not persisted today — see note below)
  - If Target is Stock: Stock location free text (UI‑only; not persisted today). Also show Retail rate.

- Quick Actions:

  - Allocate remaining:
    - If no row exists: create one with currently selected PO Line Item Job. with quantity = Remaining
    - If a row exists and is focused: fill its quantity to Remaining
  - Allocate all:
    - Convenience alias for Allocate remaining

- Previous Allocations (saved, informational):

  - Collapsible panel “Previous Allocations” summarizing saved allocations for the line
  - Source: [`purchasing_rest_purchase_orders_allocations_retrieve`](src/api/generated/api.ts:4618)
  - Collapsed by default; expanded when there are entries or when the user opens the editor

- No Save button (Autosave):
  - Inline changes autosave without explicit submit
  - Autosave occurs on:
    - Field blur
    - Popover close
    - Small debounce (e.g., 200ms) aggregating rapid edits within the same line

---

## Field Specifications

- Target

  - Select with options:
    - Stock (maps to stock‑holding job id)
    - Non‑stock jobs (from the jobs list)
  - Default when adding: selected job from PO Line

- Quantity

  - Numeric input; min 0
  - Inline validation: sum of all “this receipt” rows for the line must not exceed Remaining

- Retail rate (%) [UI‑only]

  - Visible only when Target is a non‑stock job. Also shows on stock job.
  - Default: company defaults materials_markup × 100 (see [`deliveryReceiptStore.getDefaultRetailRate`](src/stores/deliveryReceiptStore.ts:28))
  - Not sent in the current DeliveryReceiptRequest

- Stock location [UI‑only]
  - Visible only when Target is “Stock”.
  - Free‑text note for user reference
  - Not sent in the current DeliveryReceiptRequest

---

## Validation Rules (Inline)

- Non‑negative quantities
- Over‑receipt blocked:
  - Sum of “this receipt” allocations must not exceed Remaining
  - Inline error: “Exceeds remaining”
- When zero or empty:
  - Hide “This Receipt” summary block; show “+ Add” in the cell

---

## Keyboard and Accessibility

- Open/close:
  - Enter/Space on the chip opens the editor
  - Esc closes and returns focus to the trigger
- Navigation:
  - Tab/Shift+Tab across fields; Arrow keys move between rows
- Quick actions:
  - Alt+R — Allocate remaining
  - Alt+A — Allocate all
- Accessibility:
  - Popover content role="dialog", aria-labelledby, aria-describedby
  - Inline error messages announced via aria‑live="polite"
- Focus:
  - Focus moves to the first input when the editor opens
  - Preserve logical order (Target → Quantity → Rate/Location → Delete)

---

## Autosave Behavior

- Triggered on field blur or popover close, with debounce (150–300ms)
- Single‑line POST behavior:
  - Build a DeliveryReceiptRequest with allocations map containing only the edited line id
  - Use [`transformDeliveryReceiptForAPI`](src/utils/delivery-receipt.ts:22) to create the request
  - Call [`deliveryReceiptStore.submitDeliveryReceipt`](src/stores/deliveryReceiptStore.ts:96)
- On success:
  - Refresh PO detail (update received_quantity) and existing allocations
  - Remaining in the cell updates automatically
- On failure:
  - Keep the editor open; show inline error and toast; do not clear input

---

## Toasts and Inline Feedback

- Success: “Receipt saved”
- Errors:
  - “Exceeds remaining”
  - “Quantity must be greater than or equal to 0”
  - “Failed to save receipt. Try again.”

---

## Mobile Behavior

- If popover space is constrained, use a bottom drawer
- Maintain keyboard‑less usability; larger hit targets (≥ 36px)

---

## Defaults and On‑Screen Text

- Defaults:
  - New row: Target = selected PO Line Item job, Quantity = min(Remaining, 1), Retail rate = company default (for job)
- On‑screen text examples:
  - “Receipt”
  - “This Receipt”
  - “Remaining”
  - “Allocate remaining”
  - “Allocate all”
  - Error: “Exceeds remaining”
  - Error: “Quantity must be greater than or equal to 0”
  - Success: “Receipt saved”

---

## Related Plan Docs

- [`04-architecture-and-data-flow.md`](./04-architecture-and-data-flow.md)
- [`02-feature-parity-matrix.md`](./02-feature-parity-matrix.md)
- [`09-code-examples-and-focused-snippets.md`](./09-code-examples-and-focused-snippets.md)
