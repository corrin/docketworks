# Delivery Receipt Inline Allocation — Executive Summary (Refactored to Current Functionality)

This updated executive summary aligns the inline migration plan with the current, actual functionality implemented in:

- [src/views/purchasing/DeliveryReceiptFormView.vue](src/views/purchasing/DeliveryReceiptFormView.vue)
- [src/components/purchasing/DeliveryReceiptLinesTable.vue](src/components/purchasing/DeliveryReceiptLinesTable.vue)
- [src/stores/deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts)
- [src/utils/delivery-receipt.ts](src/utils/delivery-receipt.ts)
- [src/api/generated/api.ts](src/api/generated/api.ts)

Important clarifications based on the current model and generated API:

- The delivery receipt endpoint receives a record of PO-line allocations where each line payload includes:
  - total_received (number)
  - allocations: array of { job_id, quantity }
- “Stock” is represented by the stock-holding job. The UI allows editing a “stock_location” free text, but the request payload only includes job_id and quantity. If the user selects “Stock,” we map to the stock-holding job_id before sending.
- The current flow is a simple “compose allocations per line, submit once” model. No drafts/commits, no multiple persistent receipt documents.

This refactor migrates that experience inline inside the Purchase Order edit context, preserving the same data shape and validation.

---

## Scope

- Move the Delivery Receipt allocation experience inline into the PO lines table (embedded editor per line).
- Keep orchestration inside [src/views/purchasing/PurchaseOrderFormView.vue](src/views/purchasing/PurchaseOrderFormView.vue) with the existing store [src/stores/deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts).
- Maintain the existing API flows:
  - GET jobs (with stock-holding job)
  - GET existing allocations per PO
  - POST delivery receipt payload (subset of lines or a single line is allowed by sending a record with just that line)
- Preserve current validations and UX semantics:
  - Over-receipt not allowed
  - Remaining = line.quantity - line.received_quantity - existing saved allocations (not the current unsaved UI list)
  - Multiple allocations per line to different targets (jobs or stock)

No feature flag; this is a straight migration.

---

## Goals and UX KPIs

- Inline, low-friction allocation with autosave:
  - Perceived latency < 100ms (optimistic UI), network persists in the background.
  - ≤ 3 actions to fully allocate a typical line (open editor → “Allocate remaining” → save).
- Data integrity:
  - Client-side guardrails enforce non-negative quantities and no over-receipt relative to remaining.
  - Last-writer-wins for concurrent updates; on success, PO/retrieved allocations reflect server state.
- Accessibility:
  - Keyboard-first, ARIA roles, focus management, and screen-reader-friendly error messages.

---

## Target Inline UX (Right-Fit to Current Model)

- New “Receipt” column in [src/components/purchasing/PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue)
  - Cell shows a small summary chip with “This Receipt: X” and a secondary hint “Remaining: Y”
  - Clicking opens an inline popover (or expando row) with:
    - A list of CURRENT allocations for this receipt (unsaved editor state)
    - Fields per allocation row:
      - Target: Job select (includes stock-holding as the special “Stock” option)
      - Quantity: number
      - Retail rate (%): (kept as UI-only; not sent to the backend payload today; add a TODO in the payload construction and data flow to adapt the schema to include this; Comment the parameters in the end function (request), but keep it as an unused variable to facilitate to "enable" this function in the feature.)
      - Stock location: shown only when target is stock (UI-only; not sent to the backend payload today; currently is possible to see the retail rate field as well.)
    - Quick actions:
      - Allocate remaining (to stock or to selected job depending on context)
      - Allocate all (for convenience; also respects remaining)
    - Inline validation:
      - Sum of current (this receipt) allocations cannot exceed remaining
      - Non-negative quantity
- Existing allocations display (informational)
  - A small panel within the cell (collapsed by default if empty) shows saved, previous allocations (from GET allocations endpoint), matching what the current DeliveryReceipt view displays.

Autosave behavior:

- Default: Save after a short debounce when the editor closes or fields blur. The backend flow already supports partial records. Make it only available to interaction when PO is in "submitted to supplier". No draft POs with allocations. When they're done, change the status to "Fully received" or "Partially received" depending on the total remaining.

---

## Architecture (No Drafts/Commit, Reuse Existing Store)

- Inline Editor Component: AllocationCellEditor.vue (new)
  - Embedded in “Receipt” column.
  - UI-only; emits “save” with the AllocationLine payload (total_received + allocations array) for that line.
- Orchestrator: [src/views/purchasing/PurchaseOrderFormView.vue](src/views/purchasing/PurchaseOrderFormView.vue)
  - Loads PO, jobs (with stock-holding), and existing allocations via existing endpoints.
  - Provides jobs and existing allocations to the table/editor props.
  - Handles save events by calling deliveryReceiptStore.submitDeliveryReceipt with a record containing just the edited line.
  - Refreshes PO and existing allocations after save to keep remaining accurate.
- Table: [src/components/purchasing/PoLinesTable.vue](src/components/purchasing/PoLinesTable.vue)
  - Adds the “Receipt” column and mounts AllocationCellEditor per line.
  - Forwards editor events to the parent view.
- Store: [src/stores/deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts)
  - Reused as-is for:
    - fetchPurchaseOrder
    - fetchJobs (returns stock-holding + allocatable jobs)
    - fetchExistingAllocations
    - submitDeliveryReceipt (POST /purchasing/rest/delivery-receipts/ with a record of lines)
- Utility: [src/utils/delivery-receipt.ts](src/utils/delivery-receipt.ts)
  - Reuse transformDeliveryReceiptForAPI to build the DeliveryReceiptRequest.
  - Minor helper updates to support “single-line-only” payloads (see code snippets doc).

---

## API Endpoints (As Implemented)

- POST /purchasing/rest/delivery-receipts/ (alias: purchasing_rest_delivery_receipts_create)
  - Body DeliveryReceiptRequest:
    ```
    {
      "purchase_order_id": "UUID",
      "allocations": {
        "<line_id>": {
          "total_received": <number>,
          "allocations": [
            { "job_id": "UUID", "quantity": <number> },
            ...
          ]
        }
      }
    }
    ```
  - Note: retail_rate and stock_location are not part of the current request schema.
- GET /purchasing/rest/purchase-orders/:po_id/allocations/
  - Returns existing (saved) AllocationItem[] per line with rich fields (type, job_name, retail_rate, stock_location, description) for display only.
- GET /purchasing/rest/all-jobs/
  - Returns jobs[] and stock_holding_job_id. Use this to build the job select list and identify stock-holding job.

---

## Business Rules (As-Is)

- Remaining per line:
  - remaining = max(0, line.quantity - (line.received_quantity || 0)) - sum(existing saved allocations for that line)
  - Current receipt allocations (unsaved editor entries) do NOT affect remaining until posted.
- Over-receipt:
  - Disallowed. Editor blocks if sum(this receipt) allocations exceed remaining.
- Multiple allocations per line are allowed (to multiple jobs and/or stock).
- Retail rate is UI-only today (not part of request schema). It remains visible and editable in the UI for job allocations to preserve parity but is not submitted in the payload until the backend schema includes it.
- Last-writer-wins for concurrency; after POST, refresh PO and existing allocations to reflect canonical state.

---

## UX KPIs (Unchanged)

- ≤ 3 actions to fully allocate a typical line.
- Inline actions perceived < 100ms (optimistic).
- Zero navigation from the PO context.

---

## Document Set (to be reviewed/refactored to this model)

- 00-executive-summary.md (this)
- 01-questions-for-confirmation.md (trimmed to reflect resolved answers; focus on only relevant, open items)
- 02-feature-parity-matrix.md (map existing DeliveryReceipt UI → inline, without introducing new constructs)
- 03-ux-spec-inline-allocation.md (per-line editor with job/stock, quantities, retail rate UI-only, autosave)
- 04-architecture-and-data-flow.md (reuse deliveryReceiptStore, no new receipt store or batch adapter)
- 05-state-management-and-dirty-guards.md (minor: inline autosave path; rely on existing store)
- 06-api-adapter-and-endpoints.md (use only existing endpoints; remove RFC for batching/commit)
- 07-business-rules-and-edge-cases.md (only over-receipt, remaining calc, multi-job split, last-writer-wins)
- 08-error-handling-optimism-and-reconciliation.md (optimistic UI with last-writer-wins; refresh after save)
- 09-code-examples-and-focused-snippets.md (inline editor wiring to deliveryReceiptStore; single-line payload POST)
- 10-rollout-plan-kpis-and-telemetry.md (no feature flag; direct switch; optional temporary link to legacy screen if desired)
- 11-task-breakdown-and-acceptance-criteria.md (remove feature flag/batch/RFC tasks; slim down)
- 12-dev-checklist-for-review-and-release.md (align to simplified scope)
