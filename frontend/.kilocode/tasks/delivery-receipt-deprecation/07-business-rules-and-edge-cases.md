# Business Rules and Edge Cases — Inline Delivery Receipt (Current Model)

This document reflects the actual application model and generated API. It intentionally excludes concepts not present today (lots/serials, bins, multi‑location inventories, UoM conversions, ratio distributions, drafts/commit lifecycle, feature flags).

Authoritative sources:

- [DeliveryReceiptFormView.vue](src/views/purchasing/DeliveryReceiptFormView.vue:1)
- [DeliveryReceiptLinesTable.vue](src/components/purchasing/DeliveryReceiptLinesTable.vue:1)
- [deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts:1)
- [delivery-receipt.ts](src/utils/delivery-receipt.ts:1)
- [api.ts](src/api/generated/api.ts:1555)

---

## 1) Allocation Model (Per Line)

- A Purchase Order line can be allocated to:
  - One or more non‑stock jobs (by job_id)
  - Stock (by mapping to the “stock‑holding” job id returned from /purchasing/rest/all‑jobs/)
- The inline editor handles “this receipt” rows as ephemeral UI state for a single line. On autosave, it posts one DeliveryReceiptRequest with a map containing only that line.

---

## 2) Remaining Quantity (Authoritative Formula)

- Remaining for a line:
  - `remaining = max(0, line.quantity - (line.received_quantity || 0)) - sum(existingSavedAllocationsForLine)`
- Notes:
  - “existingSavedAllocationsForLine” comes from GET /purchasing/rest/purchase‑orders/:po_id/allocations/
  - Unsaved inline allocations do not change Remaining until POST succeeds.
  - Remaining is recomputed after each successful save (refresh PO + saved allocations).

---

## 3) Over‑Receipt Policy

- Over‑receipt is disallowed.
- The inline editor enforces:
  - Sum of “this receipt” quantities across rows for the line must not exceed Remaining.
  - If exceeded, show inline error “Exceeds remaining” and block autosave.
- There is no tolerance/override in scope.

---

## 4) Non‑Negative and Zero Quantities

- Each allocation quantity must be ≥ 0 (inline checked).
- Zero‑quantity rows are removed from the inline editor list before autosave (cleanliness rule).
- If all rows are zero/empty, we skip the POST for that line.

---

## 5) Job vs Stock Targets

- When Target is a job:
  - Users can optionally type a Retail rate (%) in the editor for UX parity.
  - Today, DeliveryReceiptRequest does not include retail_rate; do not send it.
- When Target is Stock:
  - Users can optionally type a Stock location note (free text).
  - Today, DeliveryReceiptRequest does not include location; do not send it.
- Both fields stay visible for parity and future schema extension.

---

## 6) Inline Autosave Behavior

- Triggers:
  - Input blur
  - Popover close
  - Debounce (150–300ms) to coalesce rapid edits
- POST shape:
  - Single‑line DeliveryReceiptRequest map:
    - `{ [lineId]: { total_received, allocations: [{ job_id, quantity }, ...] } }`
- After success:
  - Refresh PO detail and existing allocations for canonical server state.
- After error:
  - Keep editor open; show inline error and toast; allow the user to fix inputs and retry.

---

## 7) Concurrency and Conflict Policy

- Last‑writer‑wins:
  - The refresh after success ensures the UI reflects the latest canonical server values.

---

## 8) “Allocate Remaining” and “Allocate All”

- For convenience, the editor includes:
  - Allocate remaining:
    - If no row exists: create one row and set its quantity to Remaining (default Target = selected PO line chosen job).
    - If a row is focused: set that row’s quantity to Remaining.
  - Allocate all:
    - Alias of Allocate remaining for current line.
- Both commands respect the over‑receipt block.

---

## 9) Validation Summary (Inline)

- Non‑negative numbers.
- Sum(this receipt) ≤ Remaining.
- At least one row with quantity > 0 to trigger a POST.
- Target must be selected (Job or Stock). If Stock is selected, map to stock‑holding job before sending.

---

## 12) Analytics (Optional)

- Track usage of quick actions (allocate remaining/all).
- Track inline save outcomes (success/error) for basic health signals.
- Keep logging DEV‑only; avoid including user free‑text values in logs.

---

## 13) Performance Envelope

- POs are small; no pagination needed in this flow.
- Single‑line POST requests are lightweight.
- Keep debounce to minimize excessive calls on rapid edits.

---

## 14) Accessibility

- Popover uses role="dialog" with focus trap; Esc closes and returns focus to the trigger.
- Inline errors announced with aria‑live.
- Keyboard shortcuts:
  - Alt+R → Allocate remaining
  - Alt+A → Allocate all
  - Enter/Space → Open editor
  - Esc → Close editor

---

## 15) Edge Scenarios

- Remaining is 0:
  - The inline editor disables quantity inputs and shows “No remaining quantity.”
  - “Allocate remaining/all” buttons are disabled.
- Network failure mid‑edit:
  - The editor keeps user input, shows error, and allows another try.
