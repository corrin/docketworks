# JobEvent structured-delta data repair

> Self-contained handoff brief for a new Claude session — do not require context from the session that wrote it.
>
> An earlier version of this plan was written against a stale/broken dev DB and was materially wrong. A separate validation against prod contradicted every quantitative claim and drove the rewrite you're reading. **Re-verify the prod numbers in the table below against your own target DB before acting on anything here.** The pre-flight SQL under "Verification" is designed to catch the same trap.

## Context

Docketworks shipped the structured-JobEvent rewrite to production around Monday 2026-04-20. The contract: every `JobEvent` row whose `event_type` represents a state transition (`status_changed`, `quote_accepted`, `job_rejected`, `job_created`) carries structured JSON in `delta_before` / `delta_after`, so reports (starting with the Sales Pipeline Report in PR #162) read transitions from JSON instead of parsing `description` prose.

Guiding principle from the owner: **"trust the data model."** Explicitly out of scope for this repair:

- Runtime validators (`full_clean`, `save()` guards) on `JobEvent`.
- Postgres CHECK constraints.
- An `emit_*` helper layer replacing direct `JobEvent.objects.create(...)` calls.

Those all tax every save to police hypothetical bad callers. The contract is: emission code is correct, verified by tests and review, and that's it.

## What's actually true in prod (verify before acting)

Observed prod state for the four contract event types:

| event_type | total | has delta_after | has delta_before | detail populated |
|---|---:|---:|---:|---:|
| status_changed | 8,216 | 6,917 (84%) | 6,917 (84%) | 8,216 (100%) |
| job_created | 2,837 | 1,883 (66%) | — | 2,837 (100%) |
| job_rejected | 323 | 317 | 317 | 323 |
| quote_accepted | 40 | 40 | 40 | 40 |

Post-2026-04-15 emission is 100% populated for `status_changed` and `job_created`. **Live emission works.** `HistoricalJob` has ~347,650 rows over ~15 months covering 1,978 jobs — simple-history has been running for a long time, not since 2026-04-22 as the prior plan revision assumed.

**Emission-site audit.** Every `JobEvent.objects.create(...)` call site in `apps/` that emits one of the four contract event types is correct in prod today:

- `apps/job/services/job_rest_service.py:322` — `job_created`, sets `delta_after={"status": job.status}`. Correct.
- `apps/job/models/job.py:755` — inside `_record_change_event`, passes `delta_before=changes_before, delta_after=changes_after`. Correct.

The eight other call sites that a naïve grep surfaces (`xero_quote_manager`, `xero_invoice_manager`, `delivery_docket_service`, `procedure_service`, `jobevent_enrich_from_history`) emit `quote_created`, `invoice_created`, `jsa_generated`, etc. — none of which are contract event types. They're out of scope.

**Part 1 of the prior plan (audit + fix emission sites) is unnecessary. Delete it.**

## Real gaps that need fixing

### Gap 1 — 1,299 pre-2026-04-08 `status_changed` rows have NULL deltas but populated `detail`

Migration 0077 wrote `detail.changes = [{"field_name": "Status", "old_value": "Awaiting Approval", "new_value": "Approved"}, ...]` successfully for these older rows, but never back-filled the derived `delta_before` / `delta_after` — that was a separate migration (0075) that targeted a source (`HistoricalJob`) it couldn't read at the time.

Fix: a pure data migration that walks those rows, reads `detail.changes`, filters to `field_name = "Status"`, reverse-maps the display label to a raw status key via `dict((v, k) for k, v in Job.JOB_STATUS_CHOICES)`, and writes `delta_before = {"status": old_key}` / `delta_after = {"status": new_key}`. **No description-regex needed.** The structured data is already sitting in `detail`.

### Gap 2 — 949 jobs have duplicate `job_created` rows

One legacy row with NULL delta + one "backfilled from history" row with correct delta. The in-code fix for the forward path is already in place (comment at `apps/job/services/job_rest_service.py:319` — "moved from Job.save() to prevent duplicates"). The historical duplicates remain.

Decide one of:
- **Delete** the NULL-delta legacy row in each pair (simpler; loses the legacy row's `timestamp` if it differed meaningfully).
- **Merge** — write the delta from the backfill row onto the legacy row, delete the backfill row (preserves original timestamp).

Prior plan revision ignored this entirely. Needs an owner decision before the migration.

### Gap 3 — Schema design question: do `job_rejected` / `quote_accepted` carry `delta_after.status`?

Current live emission writes:

- `job_rejected` → `delta_after = {"rejected_flag": True}` (no `status` key).
- `quote_accepted` → `delta_after = {"quote_acceptance_date": "..."}` (no `status` key).

But the Sales Pipeline Report (and likely future reports) reads `delta_after.status` to derive transitions. Its `_replay_status_as_of` walks events and updates status only when `delta.get("status")` is set, so a `quote_accepted` event wouldn't move a job from `awaiting_approval` to `approved` in replay.

This is a design conflict, not a data bug. Two options:

- **Option A — Extend emission and the backfill** to also write `delta_after.status = "approved"` on `quote_accepted` and `delta_after.status = "archived"` on `job_rejected`. Implied-status-on-contract-events becomes part of the model contract. Consumers trust `delta_after.status`.
- **Option B — Consumers infer status from `event_type`** for these two types. Keeps the existing emission shape. Each future consumer has to learn the same special case.

**Needs an owner decision before the migration is written.** Option A is more consistent with "trust the data model" and removes the special case from every consumer, but it means both live emission and the backfill change. Option B is a no-op for data but taxes every future report.

## Proposal — two parts

### Part A — Resolve Gap 3 first (design decision)

Before writing any migration, pick Option A or Option B for `job_rejected` / `quote_accepted`. If Option A:

- Update `apps/workflow/views/xero/xero_quote_manager.py` (site that emits `quote_accepted`) and whatever site emits `job_rejected` to add the status key.
- Add new tests asserting the shape.
- The backfill in Part B writes the same structure onto historical rows for these two event types.

If Option B: nothing to do here; consumer code handles it; backfill in Part B skips these two event types entirely.

### Part B — Backfill migration for the 1,299-row gap (plus duplicates + optionally job_rejected/quote_accepted)

New migration, numbered against the `job` app's **actual** next number (validator reports `0080_…` is correct; the prior plan's `0216_…` was a dev-branch artifact). Check `apps/job/migrations/` for the real latest number before writing.

Dependencies: `[("job", "0079_alter_jobevent_staff_not_null")]` (or whatever the real predecessor is).

**Pass 1 — `status_changed` deltas from `detail.changes`:**

```
For each JobEvent where:
    event_type = 'status_changed'
    AND delta_after IS NULL
    AND detail->'changes' IS NOT NULL:
  find the changes[] entry whose field_name = 'Status'
  reverse-map old_value / new_value from display labels to raw keys
    via dict((label, key) for key, label in Job.JOB_STATUS_CHOICES)
  set delta_before = {"status": old_raw_key}
      delta_after  = {"status": new_raw_key}
  log rows whose Status entry is missing or whose label doesn't map
```

**Pass 2 — Duplicate `job_created` resolution:**

Per owner decision in Gap 2 — delete the NULL-delta legacy row, or merge.

**Pass 3 — (Only if Gap 3 decision = Option A):** walk existing `job_rejected` / `quote_accepted` rows, add `delta_after.status` in place.

Migration constraints (from project memory):

- Reversible via `RunPython.noop`.
- Idempotent — re-runs skip already-populated rows.
- No custom QuerySet methods (`feedback_migrations_no_custom_manager_methods.md`) — use `models.QuerySet.update(qs, ...)` or raw SQL.
- Verify via `MigrationLoader.project_state()` before merge (`feedback_migration_tests_use_live_registry.md`).
- Split from any schema alter (`feedback_separate_data_and_schema_migrations.md`) — this is pure data.
- Never `--fake` (`feedback_no_fake_migrations.md`).

## Critical files

- `apps/job/models/job_event.py` — model, **no changes**.
- `apps/job/models/job.py:755` (`_record_change_event`) — already correct.
- `apps/job/services/job_rest_service.py:319-334` — already correct; historical-duplicate source.
- `apps/job/migrations/0077_backfill_jobevent_detail.py` — populated `detail`; regex library not needed for this repair.
- `apps/job/migrations/0075_…` — superseded; leave as historical record. Add a docstring note that it couldn't run usefully against the real `HistoricalJob` at the time and has been superseded by the migration in this plan.
- **New**: `apps/job/migrations/0080_backfill_jobevent_structured_deltas.py` (verify the number).
- `apps/accounting/services/sales_pipeline_service.py` — consumer that proves the fix; **no changes here** unless Gap 3 lands as Option B (in which case the `_replay_status_as_of` helper needs to treat `event_type in ('quote_accepted', 'job_rejected')` as implied transitions).

## Verification

**Pre-flight sanity (run against whatever DB you're targeting):**

```sql
SELECT event_type,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE delta_after ? 'status') AS has_status
FROM job_jobevent
WHERE event_type IN ('status_changed', 'quote_accepted', 'job_rejected', 'job_created')
GROUP BY event_type;
```

Confirm the numbers match the prod-observation table at the top of this plan. If they don't — in particular, if you see `has_status = 0` uniformly — you are probably pointing at a stale or pre-0077 dev DB, which is what the prior plan revision did. Resolve the DB state before proceeding.

**After Pass 1:** `has_status` for `status_changed` should reach ~100%. The pre-2026-04-08 backlog is gone.

**After Pass 2:** `SELECT job_id, COUNT(*) FROM job_jobevent WHERE event_type='job_created' GROUP BY job_id HAVING COUNT(*) > 1;` returns zero rows.

**After Pass 3 (Option A only):** `has_status` for `quote_accepted` and `job_rejected` reaches 100%.

**End-to-end (dev only):** re-run the Sales Pipeline sanity check against dev:

```
DJANGO_SETTINGS_MODULE=docketworks.settings python manage.py shell -c "
from datetime import date
from apps.accounting.services import SalesPipelineService
r = SalesPipelineService.get_report(date(2026, 3, 1), date(2026, 3, 31), 4, 13)
print('snapshot:', r['pipeline_snapshot'])
print('funnel:', r['conversion_funnel'])
print('warnings:', [(w['code'], w['section'], w['count']) for w in r['warnings']])
"
```

Expected: `missing_creation_anchor` warning counts collapse to near-zero; snapshot/funnel have non-zero buckets consistent with real MSM activity.

## Open questions for the new session

1. **Gap 3 decision — Option A or Option B.** Must be resolved before writing the migration. This is a design question about the model contract, not a data-repair question.
2. **Gap 2 decision — delete or merge the 949 duplicate `job_created` pairs.**
3. **DB-target sanity.** Run the pre-flight query above on the dev DB before anything else. The prior session's audit numbers (uniformly NULL) came from a dev DB that didn't match prod; the Part-B migration will do nothing useful if run against that state because the NULL rows have NULL `detail` too and nothing to read from. If dev doesn't match prod, restore a fresh dev DB first (per memory `feedback_db_reset_method.md` — `DROP SCHEMA CASCADE`, not `dropdb`).
4. **Migration number** — verify `0080_…` is the real next number in the `job` app at the time of writing, not dev-branch state.
5. **`job_created.delta_after` coverage is only 66%** even in prod. Walk the remaining 34% before writing the migration — the NULL-delta half of the 949-job duplicate pairs accounts for ~950 rows; the other ~1,900 NULL rows are something else. Find the pattern before backfilling.

## Upstream context

- **PR #162** (Sales Pipeline Report v1) is in draft with a blocker notice pointing to this work. All review comments resolved; data repair is the last gate.
- **ADR 0013** (error-message clarity) and **ADR 0014** (explicit `else` branches) landed with that PR, unrelated to this work.
- **Prior plan revision** at this path diagnosed the problem from a broken dev DB snapshot and proposed description-regex parsing across all rows. It was wrong. This revision supersedes it. If you're reading this to execute, don't trust anything that isn't supported by the prod numbers table at the top of the file — re-verify against your target DB first.
