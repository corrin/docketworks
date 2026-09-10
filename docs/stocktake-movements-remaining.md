# feat/stocktake-movements — what this branch still owes

Work belonging to this branch and PR 151, kept out of
[`rewrite-status.md`](rewrite-status.md) so that file stays the rewrite-wide list. **This
file only shrinks**: a line is deleted the moment its item closes, and anything worth
keeping that is not a task — a ruling, a measurement — goes to
[`rewrite-history.md`](rewrite-history.md).

Delete this file when the branch merges and nothing is left in it.

## Blocking the merge

- **The E2E suite is not green from the first spec.** Three drift failures remain
  unclassified: both session-replay specs, which wait on the internal recording endpoints,
  and the person-linking one. None touches Xero.
- **Two failures need the Xero daily allowance to reset.** `purchasing/po-receipt-sync.spec.ts`
  reached "Xero sync aborted" against an expected "complete", which is the quota floor doing
  its job, and `admin/xero.spec.ts` employee refresh stalled the same way. Neither is a code
  defect. The allowance was spent by a production restore plus a full suite in one day.
- **The restore runbook's acceptance test is unrecorded** and stays so until a full suite is
  green from the first spec.

## Not blocking, but this branch's to close

- **Close the code that still reads the superseded data shape (ADR 0059).** Each line below
  is one commit: the migration that rewrites the rows, then the branch and the nullability,
  together — a half-done item is worse than an untouched one, because the migration is meant
  to be the only place that knows the old shape. Where a model and a comment disagree about
  nullability the contract is right and the branch is the suspect (ADR 0015), so never widen
  one to fit code you found.
  - No test changes needed, so cheapest to take: `job/models/job_event.py`'s
    `legacy_description` arm and its float-comparison priority
    arm; `job/services/kanban_categorization_service.py`'s dead status strings and its
    `.get(status, "draft")` default; `job/models/spreadsheet.py`'s AttributeError raised to
    mirror the old behaviour; `job/models/job.py`'s nullable `company`.
  - The largest class, and the one ADR 0059 rules on directly: columns declared nullable
    because restored rows had no value, each carrying `# noqa: DJ001 -- restored column`.
    Backfill and make `NOT NULL`, or do not have the column. Bulk is `quoting/models.py`;
    the rest are spread across the job, accounts, operations, process and purchasing models.
  - Phone grandfathering, which spans `company/models.py`'s `check_phone_assignment`,
    `company/services/person_merge_service.py`'s deliberate bypass of it,
    `xero/raw_fields.py` depending on it, and the symmetric pair in `crm/models.py` and
    `crm/api.py`. Four tests assert the grandfathering and must assert the rule instead.
    **Blocked on the owner:** production holds cross-company numbers, and per the duplicate
    process some are staff internal lines to delete rather than reassign.
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
- **One vendor's rate limit fails the whole restore gate.**
  `scripts/ops/restore_checks/check_ai_providers.py` calls `verify_provider` in a loop with
  nothing catching a refusal, so the first vendor that raises aborts the run and the
  providers behind it are never tested. A rejected credential and a rate limit deserve
  different treatment — one is misconfiguration, the other is a fact about today — so a
  blanket catch is the wrong shape.

## Watch on the next full gate run

- **The item picker failure does not reproduce alone.** `job/job-cost-entry-data.spec.ts`
  passed twice in isolation after the wage-rate fix. Four mechanisms are disproved, so it is
  only observable under a full suite. Watch it rather than chasing it on its own.
