# Fix WIP Report to Use Historical Job State

## Context

The WIP report (`apps/accounting/services/wip_service.py`) accepts a `report_date` parameter but uses **current** job `status`, `fully_invoiced`, and `rejected_flag` instead of their values as-of `report_date`. This means running the report for a past date produces incorrect results — e.g., a job archived last week won't appear in a report dated two weeks ago. Invoice aggregation also lacks a date filter.

Cost lines are already correctly filtered by `accounting_date__lte=report_date`.

## Changes

### 1. Add `_get_historical_job_states()` method to `WIPService`

Query `Job.history.model` (the `HistoricalJob` table) to bulk-fetch the most recent historical snapshot of each job as-of `report_date`. Returns a dict keyed by job UUID string with `status`, `fully_invoiced`, `rejected_flag`.

Uses `Subquery`/`OuterRef` to get the latest `history_date` per job — single query, no N+1. Convert `report_date` (date) to end-of-day datetime via `datetime.combine(report_date, time.max)` since `history_date` is a DateTimeField.

Jobs with no history record before the cutoff (didn't exist yet) are simply absent from the dict.

### 2. Modify `get_wip_data()` — use historical state for filtering

Replace the current base queryset that filters on live `fully_invoiced`, `rejected_flag`, `status`:

```python
# Before
base_qs = Job.objects.filter(fully_invoiced=False, rejected_flag=False)
    .exclude(status__in=NO_WORK_STATUSES) ...

# After
historical_states = WIPService._get_historical_job_states(report_date)
job_ids = [UUID(jid) for jid, s in historical_states.items()
           if not s["fully_invoiced"] and not s["rejected_flag"]
           and s["status"] not in NO_WORK_STATUSES]
base_qs = Job.objects.filter(id__in=job_ids)
    .exclude(latest_actual__isnull=True) ...
```

`latest_actual__isnull=True` stays on the live queryset — we need the CostSet to exist now to aggregate cost lines.

In the loop, use `historical_states[str(job.id)]["status"]` for the archived check instead of `job.status`.

### 3. Modify `_aggregate_job()` — accept and use historical status

- Add `historical_status: str` parameter
- Set `"status": historical_status` in the returned row dict
- Add `date__lte=report_date` to the invoice query

### 4. Updated imports

Add: `uuid`, `datetime`, `time`, `OuterRef`, `Subquery` (from django.db.models)

## Files to modify

- `apps/accounting/services/wip_service.py` — all changes above

## Verification

- Run existing tests: `python -m pytest apps/accounting/`
- Manual test: create a job, change its status to archived, run WIP report for a date before the status change — job should appear in active WIP
- Run WIP report for today — results should match current behavior (historical state = current state)
