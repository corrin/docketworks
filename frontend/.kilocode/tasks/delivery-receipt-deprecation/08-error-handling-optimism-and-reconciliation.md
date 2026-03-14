# Error Handling, Optimistic UI, and Reconciliation — Inline Delivery Receipt (Current Model)

Aligned with the existing app behavior and endpoints.

Authoritative sources:

- [DeliveryReceiptFormView.vue](src/views/purchasing/DeliveryReceiptFormView.vue:1)
- [DeliveryReceiptLinesTable.vue](src/components/purchasing/DeliveryReceiptLinesTable.vue:1)
- [deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts:1)
- [delivery-receipt.ts](src/utils/delivery-receipt.ts:1)
- [api.ts](src/api/generated/api.ts:1555)

---

## Objectives

- Provide immediate, intuitive inline feedback for per‑line receipt allocations.
- Maintain the simple “POST and refresh” flow with last‑writer‑wins.
- Never silently drop errors; show inline messages and toasts.
- Keep user inputs intact on failure for quick correction and retry.

---

## Optimistic UI Model (Per Line)

- The inline editor operates on ephemeral local rows (“this receipt” allocations for a single line).
- On field blur or popover close, autosave is triggered after a small debounce (150–300ms).
- While posting, keep the UI interactive; show a small busy indicator in the editor header if desired.
- Upon success, refresh the Purchase Order detail and Existing Allocations to reconcile the Remaining computation.

---

## Error Mapping and User Feedback

- Validation (400/422):
  - Exceeds remaining:
    - Inline error on the Quantity input: “Exceeds remaining”
    - Block autosave; do not send POST
  - Negative or malformed quantity:
    - Inline error: “Quantity must be greater than or equal to 0”
  - Field error display:
    - Highlight the field, show a short error under it
    - Announce via aria‑live="polite"
- Network/Server (5xx or connectivity error):
  - Toast: “Failed to save receipt. Try again.”
  - Keep editor open and preserve user input
- Not Found/Forbidden:
  - 404: toast “Resource not found”; keep input to allow reattempt if caused by transient state
  - 403: toast “Access denied”; disable further edits in this session for the affected line

---

## Concurrency and Reconciliation

- Policy: Last‑writer‑wins (same as current app)
- After a successful POST:
  - Refresh PO detail to update line.received_quantity
  - Refresh Existing Allocations to recalc Remaining using the canonical, server‑saved state

---

## Autosave and Retry Flow

- Trigger: on blur / popover close (with debounce)
- Build a single‑line DeliveryReceiptRequest map using [transformDeliveryReceiptForAPI](src/utils/delivery-receipt.ts:22)
- Call [deliveryReceiptStore.submitDeliveryReceipt](src/stores/deliveryReceiptStore.ts:96)
- Success path:
  - Toast (optional): “Receipt saved”
  - Refresh PO + Existing Allocations
- Failure path:
  - Inline error(s) and toast
  - Keep editor open; user adjusts inputs and autosave will reattempt on next blur/close

---

## Accessibility

- Popover uses role="dialog" with properly associated labels
- Inline errors:
  - Add aria‑live="polite" for error announcements
  - Focus the first invalid input when the user attempts to close with invalid state
- Keyboard:
  - Enter/Space opens editor
  - Esc closes and returns focus to trigger
  - Alt+R allocates remaining; Alt+A allocates all (optional helpers)

---

## Logging and Diagnostics

- DEV‑only console logs at debug level (omit quantity values in logs if preferred)
- Log POST attempts and outcomes with context:
  - { poId, lineId, rowsCount, totalThisReceipt, remainingAtAttempt }
- Do not log stock_location free text or other potentially sensitive user notes

---

## Minimal Guardrails

- Prevent autosave when:
  - Any quantity is negative
  - Sum(this receipt) > Remaining
- Do not send empty submissions:
  - If all row quantities are zero/empty, skip POST

---

## Copy

- allocation.inline.error.overReceipt = “Exceeds remaining”
- allocation.inline.error.nonNegative = “Quantity must be greater than or equal to 0”
- allocation.inline.error.network = “Failed to save receipt. Try again.”
- allocation.inline.success.saved = “Receipt saved”
- allocation.inline.hint.retailRate = “Not applied to saved receipt yet”
- allocation.inline.hint.stockLocation = “Note only; not saved to server”

---

This matches the current system constraints and usage patterns while delivering a faster inline UX with robust, simple error handling.
