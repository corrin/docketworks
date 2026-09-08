# Legacy inventory repair

Legacy receipt gaps record missing evidence, not reconstructed receipts. Preserve
the booked charges and quantities; keep the uncertainty visible in PO notes and
cost comments. `LegacyReceiptAdjustment` acknowledges an exact quantity difference
without creating stock, movements or charges. The audit reports these records
separately and still rejects any additional unexplained discrepancy.

Use `adhoc.inventory_cost_repair` with private manifests. Stop application and
worker writers, take a recoverable database backup, and rehearse the complete
sequence on an isolated clone first. Client identifiers and manifests do not
belong in this public repository.

1. Preview the reference manifest with `python -m adhoc.inventory_cost_repair
   references.json --database TARGET`. Add `--apply` only after the preview and
   rehearsal agree. `rows` names exact historical costs; `dead_line_id: null`
   means the original reference was absent. A replacement must independently
   match the booked position. Otherwise retain the charge as an adjustment.
   `stock_rows` names exact orphan identities and their existing opening
   movements; only their source and explanatory description change.
2. Run `manage.py audit_inventory_openings --preflight-only`, then `manage.py
   migrate`. The preflight checks cutover sources; it is not the full ledger gate.
3. Measure remaining receipt gaps from the migrated evidence. Preview a manifest
   containing `receipt_rows` with `python -m adhoc.inventory_cost_repair gaps.json
   --database TARGET --phase receipt-gaps --staff STAFF_UUID`, then apply the same
   reviewed manifest. Each row names the line, its recorded received quantity,
   the positive unexplained quantity and the reason. Notes name the repair time
   and operator, not an invented historical receipt date. Automated runs use the
   existing System Automation staff identity.
4. Run `manage.py audit_inventory_openings` and `manage.py
   reconcile_cost_summaries --all`. Compare existing costs and accounting dates,
   original stock balances and PO received quantities against the backup. New
   identities from the existing cutover migration must have zero stock on hand.
5. Run the managed E2E gate and verify that teardown restores the repaired
   baseline. Keep the pre-repair backup independently of E2E's temporary backups.

Both repair phases validate before applying and are repeatable. Changed evidence
requires another review, not a guessed replacement. Legacy adjustments are
immutable and protect their PO lines from deletion; normal receipt and reversal
commands do not edit them.

The v1 restore script accepts `INVENTORY_REPAIR_MANIFEST` for references, followed
by `INVENTORY_RECEIPT_GAP_MANIFEST` and `INVENTORY_REPAIR_STAFF` after migration.
Its final full audit remains mandatory. Do not reuse a local manifest against a
different snapshot without validating every named record.
