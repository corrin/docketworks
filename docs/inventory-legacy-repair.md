# Legacy inventory repair

Two things run against a restored snapshot before the ledger is trusted: a reviewed
manifest that repairs orphan cost references and stock sources, and a migration that
books the receipt evidence a 2025 duplicate-purchase-order defect destroyed.

The second needs no operator input. Migration
`purchasing/0015_backfill_legacy_receipt_evidence` measures each order line's gap with
the audit's own arithmetic and books one `receipt_opening` against a zero-quantity stock
identity, which is how the ledger already records "received historically, no balance
remains" (ADR 0059). It moves no balance, creates no charge, and aborts if any line holds
more evidence than its recorded received quantity.

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
   migrate`. The preflight checks cutover sources and prints the pending-openings
   figure to check the backfill against; it is not the full ledger gate.
3. Run `manage.py audit_inventory_openings` and `manage.py
   reconcile_cost_summaries --all`. Compare existing costs and accounting dates,
   original stock balances and PO received quantities against the backup. New
   identities from the cutover and backfill migrations must have zero stock on hand.
4. Run the managed E2E gate and verify that teardown restores the repaired
   baseline. Keep the pre-repair backup independently of E2E's temporary backups.

The manifest repair validates before applying and is repeatable. Changed evidence
requires another review, not a guessed replacement.

The full audit in step 3 remains mandatory however the manifest was applied. Do not
reuse a local manifest against a different snapshot without validating every named
record.
