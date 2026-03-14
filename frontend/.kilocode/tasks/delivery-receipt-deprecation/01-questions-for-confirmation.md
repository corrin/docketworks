# Questions for Confirmation — Inline Delivery Receipt (Aligned to Current Functionality)

This list only includes open items that can still affect the final UX and implementation, given the current, actual model and endpoints in:

- [src/views/purchasing/DeliveryReceiptFormView.vue](src/views/purchasing/DeliveryReceiptFormView.vue)
- [src/components/purchasing/DeliveryReceiptLinesTable.vue](src/components/purchasing/DeliveryReceiptLinesTable.vue)
- [src/stores/deliveryReceiptStore.ts](src/stores/deliveryReceiptStore.ts)
- [src/utils/delivery-receipt.ts](src/utils/delivery-receipt.ts)
- [src/api/generated/api.ts](src/api/generated/api.ts)

Non‑applicable topics removed: bins/locations hierarchy, lot/serial tracking, UoM conversions, “distribute by ratio”, “copy previous”, drafts/commit lifecycle, feature flags.

---

## 1) Over‑receipt policy (final confirmation)

- We will block over‑receipt inline (sum of “this receipt” allocations must not exceed Remaining).
- Remaining uses the same formula as the current screen:
  - remaining = max(0, line.quantity − (line.received_quantity || 0)) − sum(existing saved allocations for the line)
- Confirm there is no tolerance/override case to support now.

Proposed defaults:

- Hard block with inline error “Exceeds remaining”.

## 2) Retail rate field semantics

- The UI currently allows entering retail_rate (%) for job allocations, but the DeliveryReceiptRequest schema doesn’t accept it.
- Existing allocations returned by the API can include retail_rate for display.
- Confirm we should:
  - Keep retail_rate input in the inline editor as a UI convenience (not persisted today), or
  - Hide it for now to avoid confusion.
    R: keep it, the schema will be refactored.

Proposed default:

- Keep the field visible when target is a job. Add TODO in the code to refactor schema to accept this data. Send it to the store/service but not add it to the payload, keep it unused temporarily.

## 3) “Stock location” free text

- The inline UI shows a “Stock Location” free text when target is stock. Request schema doesn’t accept it.
- Confirm we should:
  - Keep this as a UI note only (not persisted), or
  - Remove it from the inline editor to reduce confusion.
    R: keep it, the schema will be refactored.

Proposed default:

- Keep for parity with current UI. Same notes as above.

## 4) Save granularity and timing

- To mirror the current flow and keep interactions snappy, we’ll post only the edited line via a partial DeliveryReceiptRequest (allocations map with that single line).
- Confirm “single‑line only” payloads are acceptable (same as the current DeliveryReceipt view behavior).
- Autosave:
- Default: debounce autosave on blur/close (150–300ms) to persist without pressing Save. Confirm if we should enable autosave now.

Proposed default:

- AUTOSAVE FROM THE BEGINNING. NO BUTTON TO SAVE.

R: the current PoLinesTable and PurchaseOrderFormView already handle autosave, we just need to integrate it. Autosave.

## 5) Existing allocations block in the cell

- We plan to keep a small, collapsible block that shows “Previous Allocations” summary for that line (fetched from purchasing_rest_purchase_orders_allocations_retrieve).
- Confirm this is desired in the inline cell to preserve context.

Proposed default:

- Keep it collapsed by default, expand if there are previous allocations or when the user opens the editor.

R: Yes.

## 6) After-save refresh scope

- Current screen reloads the PO and existing allocations after a receipt is posted.
- Confirm we should keep the same pattern inline:
  - After successful Save for one line, refresh:
    - The PO detail (to get updated received_quantity), and
    - Existing allocations for the whole PO (or just that line if we later add a line‑scoped fetch).

R: Yes.

Proposed default:

- Refresh PO + existing allocations (full), simple and consistent.

## 7) Error policy and concurrency

- Last‑writer‑wins is acceptable. We’ll:
  - Show error toast if a POST fails (400/422) and keep the editor open.
  - On success, reload PO/allocations to reflect server canonical values.

R: Yes.

## 8) Inline editor defaults

- When the user clicks “Add” for a line with Remaining R:

  - Default allocation:
    - Target: selected job from the existing PO line.
    - Quantity: PO line quantity.
    - Retail rate default: from company defaults (materials_markup \* 100), but keep it overridable.

- Confirm these defaults are acceptable.
  R: Agreed.

---

Please confirm the above items. If accepted, the remaining plan documents (UX spec, parity matrix, architecture, code snippets, tasks, checklist) will be fully updated to reflect this simplified, accurate model, and we will proceed to implementation accordingly.

R: I confirm.
