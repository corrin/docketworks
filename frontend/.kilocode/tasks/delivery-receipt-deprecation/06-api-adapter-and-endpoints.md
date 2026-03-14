# API Usage — Inline Delivery Receipt (Aligned to Current Model)

This document describes exactly which existing endpoints are used and how, matching the current implementation. No new endpoints, no batch RFC, no idempotency, no drafts/commit lifecycle.

Authoritative sources:

- [deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts:1)
- [delivery-receipt.ts](src/utils/delivery-receipt.ts:1)
- [api.ts](src/api/generated/api.ts:1555)

## Endpoints in Use

1. Retrieve Jobs (with stock holding)

- GET [`/purchasing/rest/all-jobs/`](src/api/generated/api.ts:4515)
- Alias: purchasing_rest_all_jobs_retrieve
- Response type: schemas.AllJobsResponse
- Used to:
  - Build Job select list for allocations
  - Identify stock-holding job (stock_holding_job_id) for “Stock” target mapping

2. Retrieve Purchase Order (detail)

- GET [`/purchasing/rest/purchase-orders/:id/`](src/api/generated/api.ts:4583)
- Alias: retrievePurchaseOrder
- Response type: schemas.PurchaseOrderDetail
- Used to:
  - Populate lines (quantity, received_quantity)
  - Update the UI after a line receipt is posted

3. Retrieve Existing Allocations (saved, informational)

- GET [`/purchasing/rest/purchase-orders/:po_id/allocations/`](src/api/generated/api.ts:4620)
- Alias: purchasing_rest_purchase_orders_allocations_retrieve
- Response type: schemas.PurchaseOrderAllocationsResponse
- Used to:
  - Render the “Previous Allocations” block for each line
  - Compute Remaining: remaining = max(0, line.quantity − (line.received_quantity || 0)) − sum(existing saved allocations for that line)

4. Submit Delivery Receipt (POST)

- POST [`/purchasing/rest/delivery-receipts/`](src/api/generated/api.ts:4523)
- Alias: purchasing_rest_delivery_receipts_create
- Request type: schemas.DeliveryReceiptRequest
- Response type: schemas.DeliveryReceiptResponse
- Used to:
  - Persist allocations for “this receipt” (inline). We submit a single-line map per autosave to minimize payload and avoid disrupting other lines.

---

## Request/Response Shapes (as implemented)

DeliveryReceiptRequest (what we POST)

```json
{
  "purchase_order_id": "UUID",
  "allocations": {
    "LINE_ID": {
      "total_received": 6.0,
      "allocations": [{ "job_id": "UUID_OF_JOB_OR_STOCK_HOLDING", "quantity": 6.0 }]
    }
  }
}
```

DeliveryReceiptResponse (what we expect back)

```json
{
  "success": true
}
```

Important:

- retail_rate and stock_location are not part of DeliveryReceiptRequest today. We keep these inputs in the UI (per product decision) but do not include them in the POST until the schema is refactored. Add a TODO to refactor the schema.

---

## Adapter/Store Usage

We do not add a new adapter layer. We reuse the existing store and helper:

- Store:

  - [useDeliveryReceiptStore.submitDeliveryReceipt](src/stores/deliveryReceiptStore.ts:96)
  - [useDeliveryReceiptStore.fetchExistingAllocations](src/stores/deliveryReceiptStore.ts:132)
  - [useDeliveryReceiptStore.fetchJobs](src/stores/deliveryReceiptStore.ts:60)
  - [useDeliveryReceiptStore.fetchPurchaseOrder](src/stores/deliveryReceiptStore.ts:39)

- Helper:
  - [transformDeliveryReceiptForAPI](src/utils/delivery-receipt.ts:22)
  - We call it with a map containing only the edited line (single-line “partial” submission).

---

## Autosave Behavior

- On blur/close of the inline editor (with a small debounce), we:
  - Build a single-line map using transformDeliveryReceiptForAPI
  - POST to purchasing_rest_delivery_receipts_create
  - On success: refresh Purchase Order and Existing Allocations

---

## Error and Concurrency Policy

- Last-writer-wins
- On error (400/422):
  - Keep the editor open and surface inline errors and a toast
- On success:
  - Refresh canonical state (PO + existing allocations) to update Remaining

---

## Notes on Future Schema Refactors

- retail_rate (% for job allocations) and stock_location (free text for stock) are displayed/edited in the UI for parity. They are not included in POST yet.
- Once the backend extends DeliveryReceiptAllocation to include these fields, we will:
  - Update transformDeliveryReceiptForAPI to include them
  - Update the store submission to send the enriched payload
  - Keep backward compatibility toggled by presence of fields in the generated schema

No further changes required to endpoints. The inline UX will continue to work with the additional fields seamlessly.
