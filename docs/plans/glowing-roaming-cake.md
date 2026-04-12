# Plan: Historical JobEvent Enrichment from SimpleHistory

## Context

We're migrating from django-simple-history (`HistoricalJob`) to our custom `JobEvent` model. Production has both systems running side-by-side: `HistoricalJob` records are created automatically on every Job save, and `JobEvent` records are created by `Job.save()._create_change_events()` for recent changes.

Three draft migrations exist on this branch (0073-0075) but are **untracked and have never run anywhere**:
- **0073**: Would backfill JobEvent from HistoricalJob (one event per changed field, generic descriptions, no staff)
- **0074**: Would add a `detail` JSONField to JobEvent
- **0075**: Would backfill `detail` by regex-parsing descriptions

**The problem**: Production's HistoricalJob table has the complete historical record going back to the beginning. Production's JobEvent table only has events from when the JobEvent system was introduced. We need to enrich the older period using HistoricalJob data.

**Goal**: Build diagnostic/experimental scripts that deeply understand both datasets, match records where overlap exists, construct validated enriched events, and prove the approach works — ready to inform a future proper migration.

## Approach: 4 Management Commands + Shared Utils

All scripts are **read-only by default**. The enrichment command has a `--commit` flag but we won't use it until we're confident. Scripts go in `apps/job/management/commands/`.

### File 1: `_history_enrichment_utils.py` (shared module, not a command)

Underscore prefix means Django won't treat it as a command. Contains:

- `FIELD_EVENT_TYPE` — field-to-event-type mapping (same as draft migration 0073)
- `FIELD_LABELS` — field-to-display-name mapping
- `DISPLAY_MAPPERS` — dict of `field_name -> callable(value) -> display_string`, derived from Job's `_FIELD_HANDLERS`:
  - `status`: `dict(JOB_STATUS_CHOICES)[value]`
  - `pricing_methodology`: `dict(PRICING_METHODOLOGY_CHOICES)[value]`
  - `client_id` / `contact_id`: lookup from pre-fetched name caches
  - `paid`, `collected`, `complex_job`, `rejected_flag`: `"Yes"` / `"No"`
  - `delivery_date`, `quote_acceptance_date`: date formatting
  - `charge_out_rate`: `f"${value}/hour"`, `price_cap`: `f"${value}"`
  - Text fields: raw string
- `safe_value(value)` — JSON serialization (Decimal, date, UUID)
- `walk_history_pairs(job_id, HistoricalJob)` — generator yielding `(prev, current, changed_fields_dict)` tuples
- `find_matching_event(job_id, event_type, timestamp, window, JobEvent)` — shared matching logic
- `build_detail_entry(field_name, old_val, new_val)` — constructs `{"field_name": ..., "old_value": ..., "new_value": ...}` using display mappers
- FK name caches: lazy-loaded `{id: name}` dicts for Client, ClientContact

Key fact: `AUTH_USER_MODEL = "accounts.Staff"`, so `HistoricalJob.history_user_id` IS the Staff ID directly.

### File 2: `jobevent_diagnostic.py` — State Analysis

Pure read-only audit. No `--commit` flag needed.

**Queries**:
1. Total JobEvent count by `event_type`
2. Events with `staff` NULL vs populated
3. Date range of JobEvent records (earliest/latest timestamp)
4. Total HistoricalJob count by `history_type` (+/~/-)
5. Date range of HistoricalJob records
6. Distinct job count in each table
7. Jobs in HistoricalJob with zero JobEvents (pre-JobEvent-era jobs)
8. Jobs with JobEvents but zero HistoricalJob records (shouldn't exist, but check)
9. Overlap period: jobs that have both HistoricalJob and JobEvent records, with date ranges

**Args**: `--job-id` (optional, restrict to one job)

### File 3: `jobevent_match_history.py` — Matching + Gap Analysis

Walks HistoricalJob pairs, detects field changes, and tries to find a matching JobEvent for each. This tells us where the overlap is and what's missing.

**Matching algorithm**:
1. For each job, walk consecutive HistoricalJob records ordered by `history_date`
2. For each changed field, derive expected `event_type` from `FIELD_EVENT_TYPE`
3. Search for JobEvent with matching `job_id` + `event_type` + `timestamp` within window
4. Score: EXACT (within 1s + deltas match), CLOSE (within window + type matches), UNMATCHED

**Output**:
- Summary counts per match tier
- Date boundary: approximate date when JobEvent system went live (where matches start appearing)
- List of UNMATCHED changes (historical changes with no JobEvent — the ones we need to backfill)
- List of matched events that could be enriched (e.g., missing staff)
- Per-job detail with `--verbose`

**Args**: `--job-id`, `--window N` (seconds, default 2), `--verbose`

### File 4: `jobevent_enrich_from_history.py` — Construct Candidate Events

For each HistoricalJob change, constructs what the JobEvent should look like. Two modes:

**Mode 1: `--dry-run` (default)** — Shows proposed events, writes nothing. This IS the validation step.

For each historical change, proposes a JobEvent with:
1. **`event_type`**: From `FIELD_EVENT_TYPE` mapping
2. **`staff`**: From `HistoricalJob.history_user_id`
3. **`timestamp`**: From `HistoricalJob.history_date`
4. **`delta_before` / `delta_after`**: Raw field values from consecutive HistoricalJob records
5. **`detail`**: Structured `{"changes": [{"field_name": "Status", "old_value": "In Progress", "new_value": "Completed"}]}` using display mappers

For changes that already have a matching JobEvent (overlap period), proposes updates instead of inserts — enriching staff and detail where missing.

**Mode 2: `--commit`** — Actually writes. Uses `bulk_update`/`bulk_create` in `transaction.atomic()` per batch.

**Safeguards**:
- Skip events that already have structured `detail` with `changes` key (don't overwrite live events)
- For FK fields where referenced object is deleted: `"Unknown Client (id=...)"` — log warning, never skip
- Pre-fetch Client/Contact names to avoid N+1

**Args**: `--dry-run` (default), `--commit`, `--job-id`, `--batch-size N` (default 500)

## Key Design Decisions

**One event per field vs one event per save**: HistoricalJob records capture the state after each save. Multiple fields can change in one save. Walking consecutive records shows all changes at once. Draft migration 0073 created one event per changed field. Modern `_create_change_events()` creates one event per save with all changes combined. The scripts should **construct one event per save** (matching the modern format) since we're building from scratch — no legacy per-field events to preserve.

**detail field**: The scripts should construct `detail` matching the modern format even though the `detail` field might not exist on production's JobEvent table yet. The constructed data validates correctness. A future migration can add the field and populate it.

**Validation is visual**: The `--dry-run` output of the enrichment script IS the validation. We inspect it for a handful of jobs, compare against what we'd expect, and iterate.

## Critical Files

- `apps/job/models/job.py` — `UNTRACKED_FIELDS` (lines 110-134), `JOB_STATUS_CHOICES` (138-149), `_create_change_events` (614-677), `_FIELD_HANDLERS` (705+)
- `apps/job/models/job_event.py` — model definition, `build_description()`, `_DESCRIPTION_BUILDERS`
- `apps/job/migrations/0073_backfill_jobevent_status_from_historicaljob.py` — draft migration with `FIELD_EVENT_TYPE` mapping and matching logic (reference, not to import)
- `apps/job/management/commands/set_paid_flag_jobs.py` — command pattern to follow

## Verification

1. Run `jobevent_diagnostic` — understand current state, confirm HistoricalJob has data, see date ranges
2. Run `jobevent_match_history` — verify matching logic, identify the overlap boundary date, quantify gaps
3. Run `jobevent_enrich_from_history --dry-run --job-id <specific_job>` — inspect proposed events for a few known jobs
4. Manually compare proposed events against HistoricalJob records in Django shell
5. Once confident, use the validated logic to write a proper migration
