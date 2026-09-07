# KAN-358 implementation plan

WRITTEN BY AI — trust nothing below.

Ticket: https://docketworks.atlassian.net/browse/KAN-358

Prepared against fetched `origin/main` at `e6db50f` on
`fix/KAN-358-po-receipt-status`. This document plans implementation; no bug fix
or regression test has been written or run in this planning slice.

## Verified by source inspection

- `process_delivery_receipt` locks the PO, records received quantities and
  allocations, then calls `recompute_purchase_order_status`, which derives the
  receipt status and advances `updated_at`.
- The reconciliation task selects locally raised, non-draft/non-deleted orders
  with no agreement or an agreement older than `updated_at`.
- `XeroPurchaseOrderManager` sends either received status as `AUTHORISED`.
  `_save_po_with_xero_data` stamps agreement after the provider returns without
  checking which version was sent.
- Once no unsent change is detected, `_purchase_order_sync_values` accepts
  Xero's status. Both `AUTHORISED` and `BILLED` map to `submitted`.
  The model's `xero_status` contract explicitly separates accounting from receipt.
- The current sync-direction tests cover BILLED on an unreceived order, but
  contain no receipt → successful push → inbound pull regression.
- `update_purchase_order` locks and checks the ETag, saves the edit, and queues
  a push. A failed queued push therefore needs the reconciliation safety net.

These are code findings, not a fresh sandbox reproduction. PR #142's release
hold and the previous quota failure are reported by the ticket/handoff; current
sandbox credentials, quota and affected stored rows have not been inspected.

## Proposed implementation

1. Write the failing regressions below first. Drive receipt and edit services
   with their real ETag preconditions; mock only the provider/queue boundaries
   in hermetic tests. Record the expected failures before implementing.
2. In `_purchase_order_sync_values`, omit incoming workflow `status` when any
   PO line has positive `received_quantity`. Continue recording `xero_status`
   and importing the other permitted fields. Preserve existing unsent-edit
   protection and strict status validation. Keep receipt status calculation in
   purchasing's existing owner; do not reproduce its arithmetic in Xero.
3. Capture the PO instance's `updated_at` immediately before building the
   payload. Pass that captured version explicitly into success persistence.
   Save valid Xero identity, tenant and URL without advancing the PO ETag;
   condition the agreement update on the captured `updated_at`. On mismatch,
   preserve the existing agreement, log the deferred acknowledgement, and let
   the existing sweep resend. Cover create and update responses and retain
   zero-UUID handling. Do not hold a database lock across the vendor request.
4. Inspect affected stored rows before declaring data repair unnecessary.
   GPT: preserving a status cannot repair one already reverted to submitted.
   If affected rows exist, repair through the canonical receipt-status owner
   with a reviewed dry-run and verification, following ADR 0015; do not hide
   corrupt status through a read-time fallback.

GPT: quantity evidence defines recorded receipt more reliably than checking
the status label whose overwrite is the defect. A conditional acknowledgement
prevents an in-flight edit from being declared delivered; it does not establish
serialization of overlapping outbound requests. Include an out-of-order
response regression so an older response cannot erase a newer unsent version.

## Acceptance tests

Each test states the business regression (ADRs 0025/0052). These extend the
ticket's acceptance list; successful execution remains required.

| Layer / existing home | Test and observable guarantee |
| --- | --- |
| Service / `apps/xero/tests/test_purchase_order_sync_direction.py` | Parameterize partial/full receipt against AUTHORISED and BILLED after successful push agreement: receipt status survives inbound transform. |
| Service / same file | VOIDED on a receipted PO records `xero_status=VOIDED` while preserving receipt status, quantities and the receipt's stock/job cost records. |
| Service / same file | Unreceipted orders still accept normal Xero status transitions, including VOIDED; BILLED never invents receipt. Retain incoming-edit and unsent-edit regression coverage. |
| Service / `apps/xero/tests/test_purchase_order_reconcile.py` | During provider execution, save a real local edit and suppress its immediate queued push. Verify the first payload lacks that edit, the sweep selects the order, and the retry payload contains it. |
| Service / same file | With no concurrent edit, a successful create/update preserves identity and URL, advances agreement without changing the ETag, and leaves the order out of the sweep. |
| Service / same file | A successful response after a concurrent edit retains valid Xero identity/URL but leaves the edit unsent; an older response completing after a newer push does not hide a subsequent unsent edit. |
| Service / same file | Provider refusal does not acknowledge the edit; the sweep can retry. |
| Live integration / `apps/xero/tests/test_purchase_order_integration.py` | Extend the existing sandbox scenario through real partial and full receipts, application push, and application inbound pull. Read back AUTHORISED from Xero and verify local receipt status, quantities and allocations persist. Reuse existing credential fixtures and production/write guards. |
| Browser / new `frontend/tests/e2e/purchasing/po-receipt-sync.spec.ts` | Create and receipt a PO through the real UI/API, run the real application Xero push/pull through the existing supported sync controls, reload detail/list and verify the received label survives. Cover partial and full receipt. Establish how the existing UI exposes receipt and sync before implementation; if a required control is absent, record that missing capability rather than substituting a mocked round trip. |

GPT: the browser case is owed by ADR 0026 because the defect changes the
operator's received/outstanding view. The existing integration scenario proves
the vendor boundary but does not itself assert the browser's displayed result.
The ticket's observation that no current E2E drives this path identifies a gap.

## Validation and handoff

1. Run the new focused hermetic tests red, implement, then run them green.
   Prove each safeguard matters by temporarily removing it and observing the
   corresponding regression fail (ADR 0052).
2. Run the commit tier and `uv run pytest apps/xero apps/purchasing`.
   Commit coherent verified slices with explicit paths and all hooks enabled.
3. Broaden to `uv run pytest`. Run
   `./scripts/ops/run_integration_tests.sh apps/xero/tests/test_purchase_order_integration.py`
   against the sandbox, then the required integration tier before merge.
   Use the harness's execution settings; never enable `XERO_READONLY`.
4. Run the new browser spec and the full E2E release gate via
   `./scripts/ops/run_e2e.sh`, plus the push-tier migration check.
5. Record actual results and any credential/quota refusal in the PR and
   rewrite task list. A fresh quota window is a gate to complete, not a waiver.
   Keep the promotion hold until the fix and required verification pass.
   Delete the KAN-358 task entry only when the work is complete.

Applicable authorities read: ADRs 0003, 0012, 0015, 0017, 0019, 0024–0026,
0028, 0039, 0043, 0050–0053, 0055 and 0056, plus CLAUDE.md and the ADR index.
Keep this fix in the current ownership slice under ADR 0055; no new provider
abstraction, credential source, retry system or schema column is planned.


## Implementation inspection updates (2026-09-07)

- The existing Fully Received dropdown in `PoSummaryCard` calls
  `update_purchase_order` and automatically allocates lines to jobs or stock.
  `XeroPage` has an admin-wide inbound sync control. No frontend feature or route
  calls the quantity-based delivery-receipt endpoint. Browser coverage can drive
  the full-receipt shortcut; the proposed partial-receipt browser case is blocked
  by a missing workflow, not by a missing test selector.
- The owner explicitly ruled that stock is never deleted, only moved, and
  proposed a stocktake job for found/missing stock. Existing repeat-receipt and
  allocation-deletion paths physically delete stock. Receipt/stocktake workflow
  design must address those paths; do not drive repeat receipts over existing
  stock as part of this fix's live verification. Partial and full sandbox cases
  should use fresh orders, with one receipt each.
- Development data inspection found 293 positive-receipt orders with non-receipt
  labels: 217 submitted and 76 draft. Sixteen submitted orders are linked to Xero
  with AUTHORISED; the other 277 have no recorded Xero status. Repair is necessary;
  this evidence neither attributes every mismatch to KAN-358 nor audits production.
  Keep data review/application and release verification open until performed.
