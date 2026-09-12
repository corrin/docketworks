# feat/stocktake-movements — what this branch still owes

Work belonging to this branch and PR 151, kept out of
[`rewrite-status.md`](rewrite-status.md) so that file stays the rewrite-wide list. **This
file only shrinks**: a line is deleted the moment its item closes, and anything worth
keeping that is not a task — a ruling, a measurement — goes to
[`rewrite-history.md`](rewrite-history.md).

Delete this file when the branch merges and nothing is left in it.

## Blocking the merge

- **The E2E suite is not green from the first spec.** 165 passed and 2 failed on
  2026-09-12, against 20 failures two runs earlier. What is left:
  - `purchasing/pickup-address.spec.ts:29` — the selection modal never opens. A real
    failure, not the environment: it failed the previous gate too, when it was wrongly
    put down to the disconnected Xero tenant.
  - `admin/xero.spec.ts:57` — the 409 retry waited on the button rather than the server,
    fixed in `07ae5fb` and unproven, because proving it spends a whole employee refresh
    against the call budget this branch already owes a decision on.
- **The restore runbook's acceptance test is unrecorded** and stays so until a full suite is
  green from the first spec.

## Not blocking, but this branch's to close

- **Stocktake review resolution.** Add stocktake previews and conflict reconciliation, and
  complete the approved regression coverage. Verify stock search and pagination, the write
  contracts, and the history and retirement controls through the browser. Run the updated
  browser specs including product-to-TBC price overrides, the full managed E2E gate, and the
  live PO and item-import integrations.
- **Complete the Xero detail refresh's live verification, against an approved call budget.**
  Run the employee integration regression through the vendor-call ledger, then
  `admin/xero.spec.ts` and the applicable timesheet browser checks including responsive
  screenshots. Implementation and local checks are already in
  [`rewrite-history.md`](rewrite-history.md); the owner authorised zero live calls for the
  slice itself, so this needs a budget agreed first. Design is in
  [the plan](plans/2026-09-09-xero-detail-refresh.md).
- **Close the code that still reads the superseded data shape (ADR 0059).** Each line below
  is one commit: the migration that rewrites the rows, then the branch and the nullability,
  together — a half-done item is worse than an untouched one, because the migration is meant
  to be the only place that knows the old shape. Where a model and a comment disagree about
  nullability the contract is right and the branch is the suspect (ADR 0015), so never widen
  one to fit code you found.
  - No test changes needed, so cheapest to take: `job/models/job_event.py`'s
    float-comparison priority arm;
    `job/services/kanban_categorization_service.py`'s dead status strings and its
    `.get(status, "draft")` default; `job/models/spreadsheet.py`'s AttributeError raised to
    mirror the old behaviour; `job/models/job.py`'s nullable `company`.
  - The largest class, and the one ADR 0059 rules on directly: columns declared nullable
    because restored rows had no value, each carrying `# noqa: DJ001 -- restored column`.
    Backfill and make `NOT NULL`, or do not have the column. Bulk is `quoting/models.py`;
    the rest are spread across the job, accounts, operations, process and purchasing models.
  - Phone grandfathering — **not as described here until today, and the description was
    the dangerous part.** Production was scanned 2026-09-12 and holds ten colliding
    numbers: one own endpoint to delete, three duplicate contacts to merge in Xero, one
    still unresolved, and **five that are not data faults at all**. Those five are one
    shape — one person, several real accounts, one mobile — which is ordinary in this
    customer base and keeps arriving through the Xero sync. Removing the grandfathering
    under "one number, one company" would force five wrong edits, deleting a real
    customer's real number or merging businesses that are not the same business, before
    it caught anything real. The guard was also chosen deliberately for exactly these
    cases; the earlier decision record names Derek and Guardsman as the example.
    So the rule is the suspect, not the guard. Under **one number, one person, who may
    link to several companies**, four of the five become legal rather than grandfathered
    and the exception disappears instead of being preserved — which is what ADR 0059
    actually wants. That is a model change across `company/models.py`'s
    `check_phone_assignment`, `person_merge_service.py`'s bypass, `xero/raw_fields.py`
    and the pair in `crm/models.py` and `crm/api.py`, with the four tests asserting the
    new rule. **Still owed first:** whether Derek is invoiced personally — if not,
    Derek Skaife folds into Guardsman — and which side of 027 932 2222 is the typo.
  - The rest, each with tests that change alongside: `diagnostics/services/db_scrubber.py`'s
    per-value conformance gate; the event-absence fallbacks in `accounting/services/`
    `job_aging_service.py` and `sales_pipeline_service.py`;
    `timesheet/services/hour_categories.py`'s public-holiday precedence branch;
    `quoting/services/product_parser.py`'s work-list selector; and the scattered remainder
    including `job/services/month_end_service.py` and `core/uploads.py`.
- **A draft row loses its component state the instant it persists.**
  `CostLineGrid.tsx`, `SmartTimesheetTable.tsx` and `PoLinesTable.tsx` key a row by its local
  id while it is a draft and by the server id once saved, and the table renders on that key,
  so the row unmounts and remounts. `StocktakeGrid.tsx` shows the stable shape. A user typing
  a value and clicking a control in the same row loses whatever that control opened. Only the
  cost grid has a spec near it, and that spec fails for an unrelated reason, so nothing is
  watching the other two.

## Owed after promotion, not before merge

These cannot close until the branch is in production, so they outlive the merge. **They move
back to [`rewrite-status.md`](rewrite-status.md) when the branch merges — they are not
deleted with this file**, which is the one exception to the shrinking rule above.

- **KAN-360: prove the dropbox sync root mode on the host.** The fix landed on this branch in
  `3fea474` and is gated, but only a live `instance.sh reconfigure` against msm-prod shows
  that a provisioning run now leaves scanner delivery working. Run `verify-instance.sh msm
  prod` after it and confirm the sync-root check passes.
