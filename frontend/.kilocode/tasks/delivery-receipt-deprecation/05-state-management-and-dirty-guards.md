# State Management and Dirty Guards — Inline Delivery Receipt (Current Model)

This plan reuses the existing delivery receipt store and utilities. No new store is introduced. Inline editor manages per‑line UI state and triggers autosave that posts a single‑line payload using the current API.

Authoritative sources:

- [`DeliveryReceiptFormView.vue`](src/views/purchasing/DeliveryReceiptFormView.vue:1)
- [`DeliveryReceiptLinesTable.vue`](src/components/purchasing/DeliveryReceiptLinesTable.vue:1)
- [`deliveryReceiptStore.ts`](src/stores/deliveryReceiptStore.ts:1)
- [`delivery-receipt.ts`](src/utils/delivery-receipt.ts:1)
- [`api.ts`](src/api/generated/api.ts:1555)

Out of scope: drafts/commit lifecycle, batch endpoints, idempotency keys, feature flags.

---

## Store Strategy

- Reuse [`useDeliveryReceiptStore`](src/stores/deliveryReceiptStore.ts:22):

  - fetchPurchaseOrder(id)
  - fetchJobs()
  - fetchExistingAllocations(poId)
  - submitDeliveryReceipt(purchaseOrderId, singleLineReceiptMap)

- No separate “allocations store.” The inline editor holds ephemeral per‑line allocation rows (UI state), then invokes submitDeliveryReceipt on autosave.

- Derived data:
  - Remaining per line computed in the component using the same formula:
    - `remaining = max(0, line.quantity - (line.received_quantity || 0)) - sum(existingSavedAllocationsForLine)`

---

## Autosave Flow (Per Line)

- Triggers:

  - Field blur
  - Popover close
  - Small debounce (150–300ms) to coalesce multiple keystrokes

- Build a single‑line DeliveryReceiptRequest using [`transformDeliveryReceiptForAPI`](src/utils/delivery-receipt.ts:22):

  - Input: `{ [lineId]: { total_received, allocations: [{ job_id, quantity }, ...] } }`
  - Note: `retail_rate` and `stock_location` remain UI‑only (not sent today)

- Call [`deliveryReceiptStore.submitDeliveryReceipt`](src/stores/deliveryReceiptStore.ts:96):
  - On success: refresh PO detail and existing allocations (entire PO for simplicity)
  - On error: show inline errors within the editor and a toast; keep editor open

---

## Dirty State and Navigation Guards

- Because autosave is immediate on blur/close, we avoid introducing a new route‑level “unsaved changes” guard for the inline editor.
- If inputs are invalid (e.g., over‑receipt), we block autosave and show inline errors; closing the popover without fixing leaves no partial server state.
- The existing PO lines autosave in [`PurchaseOrderFormView.vue`](src/views/purchasing/PurchaseOrderFormView.vue:127) continues to run unaffected (it handles PO line edits, not receipt allocations).

---

## Caching

- Jobs and existing allocations are already fetched and held by the orchestrator view:
  - Use [`deliveryReceiptStore.fetchJobs`](src/stores/deliveryReceiptStore.ts:60)
  - Use [`deliveryReceiptStore.fetchExistingAllocations`](src/stores/deliveryReceiptStore.ts:132)
- No additional caches needed for the inline editor.

---

## Error and Concurrency Policy

- Last‑writer‑wins, consistent with current behavior:
  - On POST failure: inline error + toast; allow user to adjust and retry.
  - On POST success: refresh PO + existing allocations to present server canonical state.

---

## Minimal Responsibilities

- Inline editor:

  - Maintain UI state (this‑receipt rows)
  - Validate inputs (non‑negative, not exceeding remaining)
  - Emit autosave requests (single line)

- Table:

  - Provide per‑line editor with jobs, existing allocations, and remaining resolver
  - No direct API calls

- Orchestrator view:
  - Provide jobs and existing allocations to table/editor
  - Submit requests via store
  - Refresh on success
