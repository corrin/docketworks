# Architecture and Data Flow — Inline Delivery Receipt (Aligned to Current Model)

This refactor keeps the current data model and endpoints intact. We only change the UX to be inline inside the PO view while reusing the existing store and utilities.

Authoritative sources:

- [`DeliveryReceiptFormView.vue`](src/views/purchasing/DeliveryReceiptFormView.vue:1)
- [`DeliveryReceiptLinesTable.vue`](src/components/purchasing/DeliveryReceiptLinesTable.vue:1)
- [`deliveryReceiptStore.ts`](src/stores/deliveryReceiptStore.ts:1)
- [`delivery-receipt.ts`](src/utils/delivery-receipt.ts:1)
- [`api.ts`](src/api/generated/api.ts:1555)

Non‑applicable constructs: drafts/commit lifecycle, bins/locations hierarchy, lot/serial, UoM conversion, ratio distribution, copy‑previous, feature flags.

---

## Overview

- Orchestrator: [`PurchaseOrderFormView.vue`](src/views/purchasing/PurchaseOrderFormView.vue:1)

  - Loads PO and jobs
  - Fetches existing allocations (historical/saved)
  - Passes jobs and existing allocations to the table
  - Receives per‑line allocation changes from the inline editor and submits them via the existing deliveryReceiptStore
  - Refreshes PO and allocations after each save

- Table host: [`PoLinesTable.vue`](src/components/purchasing/PoLinesTable.vue:1)

  - Adds a new “Receipt” column
  - Embeds the inline editor component per row
  - Emits simple events to the parent view (no API calls)

- Inline editor: AllocationCellEditor.vue (new)

  - Popover editor for “this receipt” allocations for a single line
  - Fields:
    - Target: Job or Stock (maps to stock‑holding job id)
    - Quantity
    - When Job: Retail rate (%) — UI‑only for now
    - When Stock: Stock location — UI‑only for now
  - Quick actions: Allocate remaining / Allocate all
  - Autosave on blur/close with debounce
  - Emits a single “line payload” suitable for POST

- Store: [`useDeliveryReceiptStore`](src/stores/deliveryReceiptStore.ts:22)

  - Existing methods reused:
    - fetchPurchaseOrder
    - fetchJobs (returns stock‑holding + allocatable jobs)
    - fetchExistingAllocations
    - submitDeliveryReceipt (POST DeliveryReceiptRequest)

- Utility: [`transformDeliveryReceiptForAPI`](src/utils/delivery-receipt.ts:22)
  - Build a DeliveryReceiptRequest with a map of `{ [lineId]: DeliveryReceiptLine }`
  - We will pass only the edited line in this map (partial post)

---

## Data Flow (Per Line)

1. Render

   - Orchestrator loads PO, jobs, and existing allocations
   - PoLinesTable renders with props: lines, jobs, existingAllocations
   - Each line mounts AllocationCellEditor with:
     - remaining (derived)
     - this‑receipt local allocations (editor’s local state)
     - previous allocations summary (from existingAllocations)

2. Edit (inline)

   - User edits target/qty (and UI‑only fields)
   - Inline validation:
     - Non‑negative qty
     - Sum(this receipt) ≤ Remaining

3. Autosave

   - On blur/close (or after short debounce), editor builds a single‑line map:
     - `{ [lineId]: { total_received, allocations: [{ job_id, quantity }, ...] } }`
   - Orchestrator calls:
     - `deliveryReceiptStore.submitDeliveryReceipt(poId, singleLineMap)`

4. Reconciliation
   - On success:
     - Orchestrator refreshes PO detail and existing allocations
     - Remaining updates in the cell summary
   - On error:
     - Inline error and toast shown
     - Editor remains open; user can adjust values

---

## Contracts: Props and Emits

### PoLinesTable.vue

Props:

- `lines`: PurchaseOrderLine[]
- `jobs`: JobForPurchasing[]
- `existingAllocations`: Record<lineId, AllocationItem[]>

Emits:

- `receipt:save` — payload `{ lineId: string, editorState: { allocations: { target: 'job'|'stock', job_id?: string, quantity: number, retail_rate?: number, stock_location?: string }[] } }`
  - Parent converts editorState → DeliveryReceiptRequest (single‑line map) and submits

### AllocationCellEditor.vue

Props:

- `line`: PurchaseOrderLine (to compute remaining with existing allocations)
- `jobs`: JobForPurchasing[]
- `existing`: AllocationItem[] (previous saved allocations)
- `defaultRetailRate`: number (from company defaults)
- `stockHoldingJobId`: string

Emits:

- `save` — editorState for this line (UI‑shape)
- `close` — for focus management

---

## Remaining Calculation

- Same as current:
  - `remaining = max(0, line.quantity - (line.received_quantity || 0)) - sum(existingSavedAllocationsForLine)`
  - Unsaved editor allocations do not affect remaining until POST succeeds

---

## Error Handling & Concurrency

- Last‑writer‑wins
- On POST error (400/422):
  - Inline error and toast; keep editor open
- After success:
  - Refresh PO and existing allocations (full refresh for simplicity)

---

## Performance

- Per‑line POST on save (minimal payload)
- Small POs (no pagination concerns)
- Debounce autosave to avoid excessive calls on rapid edits

## What We Explicitly Do Not Add

- No new stores (we reuse deliveryReceiptStore)
- No new adapter/layer: we call store methods the same way the legacy screen does
- No batch API proposals
- No feature flags

---

## File Impacts

- Add: `src/components/purchasing/AllocationCellEditor.vue`
- Modify: [`src/components/purchasing/PoLinesTable.vue`](src/components/purchasing/PoLinesTable.vue:1) — add “Receipt” column and child component mount
- Modify: [`src/views/purchasing/PurchaseOrderFormView.vue`](src/views/purchasing/PurchaseOrderFormView.vue:1) — fetch existing allocations, pass to table, handle receipt:save, refresh after success
- Reuse: [`src/stores/deliveryReceiptStore.ts`](src/stores/deliveryReceiptStore.ts:1), [`src/utils/delivery-receipt.ts`](src/utils/delivery-receipt.ts:1)
