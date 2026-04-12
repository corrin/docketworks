# Drop HistoricalJob, Use JobEvent for Historical State

## Context

The WIP (Work In Progress) report is a legal accounting requirement — it calculates the value of unbilled work as at a given date (typically month-end). This is a balance sheet asset; all data must reflect the state as of the report date, not current state.

The current WIP service (`apps/accounting/services/wip_service.py`) uses django-simple-history's `HistoricalJob` to reconstruct job status as of the report date. This is the **only consumer** of `HistoricalJob` in application code.

Problems with the current approach:
- `fully_invoiced` in HistoricalJob is stale — it's a cached flag only recalculated on Xero sync, and the "no invoices" path uses `QuerySet.update()` which bypasses SimpleHistory entirely
- `rejected_flag` has the same staleness risk
- The WIP report already independently calculates invoiced amounts from the Invoice table — the `fully_invoiced` filter is redundant and introduces wrong exclusions
- The report mixes historical state (status from HistoricalJob) with current state (job.name, job.client, job.latest_actual) — inconsistent
- HistoricalJob creates a full row copy on every Job save, which is expensive for what amounts to one query

Meanwhile, `JobEvent` already tracks business events on jobs but has gaps:
- `status_changed` events store display names in prose descriptions, no structured data
- Multiple code paths change status without creating any JobEvent at all
- The `if staff:` guard in `Job.save()` silently skips change detection — a fail-early violation

## Design

### 1. Add structured deltas to status-related JobEvents

`_handle_status_change` in `apps/job/models/job.py` currently creates events with description-only. Change to include structured JSON:

```python
JobEvent.objects.create(
    job=self,
    event_type="status_changed",
    description=f"Status changed from '{old_display}' to '{new_display}'",
    staff=self._current_staff,
    delta_before={"status": old_status},
    delta_after={"status": new_status},
)
```

Similarly for `job_rejected`:
```python
delta_before={"rejected_flag": False},
delta_after={"rejected_flag": True},
```

And for `job_created` events (in `JobRestService.create_job`):
```python
delta_after={"status": job.status},
```

### 2. Fix code paths — require staff, always create events

The `if staff:` guard on `_create_change_events` (job.py:509) is a silent failure. Remove it — change detection should always run for existing job saves.

**Code paths to fix:**

| Location | Current problem | Fix |
|---|---|---|
| `Job.save()` line 509 | `if staff:` skips change detection | Always run `_create_change_events`, staff can be None |
| `kanban_service.update_job_status` | Doesn't pass staff | Add `staff` parameter, pass from view (`request.user`) |
| `kanban_service.reorder_job` | Doesn't pass staff | Add `staff` parameter, pass from view (`request.user`) |
| `job_service.archive_complete_jobs` | Doesn't pass staff | Add `staff` parameter, pass from view (`request.user`) |
| `auto_archive_service` | Creates event manually with staff=None | OK as-is — system operation, no user. But should use structured deltas |
| `job_rest_service.accept_quote` | Creates event manually, no deltas | Add structured deltas to the `quote_accepted` event |

**View changes required:**

| View | Location | Change |
|---|---|---|
| `KanbanJobStatusUpdateView` | `kanban_view_api.py:133` | Pass `request.user` to `update_job_status` |
| `KanbanJobReorderView` | `kanban_view_api.py:207` | Pass `request.user` to `reorder_job` |
| `ArchiveCompleteJobsAPIView` | `archive_completed_jobs_view.py:64` | Pass `request.user` to `archive_complete_jobs` |

### 3. Remove duplicate event creation on REST delta path

Currently when status changes via the REST API, two events are created:
1. `job_updated` with structured deltas (from `_build_and_apply_delta` in job_rest_service)
2. `status_changed` with prose only (from `_handle_status_change` in model save)

After this change, `_handle_status_change` will create `status_changed` with structured deltas. The `job_updated` event from the delta path will also contain status in its delta. This is fine — `status_changed` is the canonical event type for WIP queries, and `job_updated` captures the broader change context for the timeline.

### 4. Backfill migration

Write a data migration that:

1. Reads HistoricalJob records ordered by `(id, history_date)`
2. For each job, identifies the first record → creates/updates a `job_created` event with `delta_after={"status": first_status}`
3. For consecutive records where status changed → creates `status_changed` events with structured `delta_before`/`delta_after`, using the `history_date` as the event timestamp
4. For records where `rejected_flag` changed to True → creates `job_rejected` event with structured deltas
5. Skips creating events that already exist (dedup by job + timestamp + event_type)

This migration runs **before** dropping HistoricalJob.

### 5. Rewrite WIP service

Replace the HistoricalJob query with a JobEvent-based approach:

```python
# Get the latest status_changed or job_created event per job before report_date
latest_status_events = (
    JobEvent.objects.filter(
        event_type__in=["status_changed", "job_created"],
        timestamp__lte=report_datetime,
        delta_after__has_key="status",
    )
    .order_by("job_id", "-timestamp")
    .distinct("job_id")
)
```

For each event, read `delta_after["status"]` to get the job's status as of the report date.

For rejected_flag: check if a `job_rejected` event exists for the job with `timestamp__lte=report_datetime`.

Drop the `fully_invoiced` filter entirely — the calculation already handles this via `net_wip = gross - invoiced`.

**Other current-state issues to fix:**
- `job.name` and `job.client` — these use current values. For accounting accuracy these should arguably be historical too. However, job names and clients rarely change, and HistoricalJob didn't solve this either (the code fetches current Job objects at line 84-91). Accept current state for name/client as a known limitation — document it, don't pretend it's historical.
- `job.latest_actual` for cost line queries — CostLines are append-only (no edits/deletes in normal operation), and `latest_actual` doesn't change once set. The `accounting_date` filter is the real historical boundary. This is correct.

### 6. Drop HistoricalJob

**Sequencing matters.** The `HistoricalRecords()` field on Job is what registers the `HistoricalJob` model with Django. It must stay until:
- Backup restore completes (needs the model to load `job.historicaljob` fixture data)
- Backfill migration 0073 runs (uses `apps.get_model("job", "HistoricalJob")`)

Steps:
1. **Now:** Restore `history = HistoricalRecords()` on Job model — it was removed prematurely
2. **After backfill is verified:** Remove `HistoricalRecords()` from Job model + add migration to drop the table, in one step
3. Leave `simple_history` in INSTALLED_APPS — still used by Staff, Form, FormEntry, Procedure

### Files to modify

- `apps/job/models/job.py` — remove `if staff:` guard, add structured deltas to `_handle_status_change` and `_handle_boolean_change` for rejected, remove `HistoricalRecords`
- `apps/job/models/job_event.py` — no model changes needed (delta fields already exist)
- `apps/job/services/kanban_service.py` — add `staff` param to `update_job_status` and `reorder_job`
- `apps/job/services/job_service.py` — add `staff` param to `archive_complete_jobs`
- `apps/job/services/auto_archive_service.py` — add structured deltas to manually created event
- `apps/job/services/job_rest_service.py` — add structured deltas to `job_created` and `quote_accepted` events
- `apps/job/views/kanban_view_api.py` — pass `request.user` to kanban service calls
- `apps/job/views/archive_completed_jobs_view.py` — pass `request.user` to archive call
- `apps/accounting/services/wip_service.py` — rewrite to use JobEvent
- New migration: backfill status events from HistoricalJob
- New migration: drop HistoricalJob table

### Verification

1. **Backfill correctness**: Compare HistoricalJob status transitions against generated JobEvents for a sample of jobs
2. **WIP report**: Run WIP for a past date using both old (HistoricalJob) and new (JobEvent) implementations, compare results
3. **Event creation**: Test each code path (kanban drag, kanban reorder, archive, auto-archive, REST delta, quote accept) and verify a `status_changed` event with structured deltas is created
4. **Existing tests**: Run `tox -e test -- apps/job/tests/ apps/accounting/tests/` — existing WIP and job tests must pass
