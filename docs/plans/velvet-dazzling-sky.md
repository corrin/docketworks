# Fix JobEvent backfill (migration 0073)

## Context

The WIP report queries `JobEvent.delta_after` for historical job status. All existing `status_changed` and `job_created` events have `delta_after = None`. Migration 0073 backfills these from HistoricalJob but has two bugs.

## Bug 1: DISTINCT broken by default ordering (line 65)

HistoricalJob has `Meta.ordering = ('-history_date', '-history_id')`. Postgres includes ordering columns in DISTINCT, so `list(values_list('id').distinct())` returns 338k rows instead of 1,915.

**Fix**: `order_by()` before `distinct()`. Already applied.

## Bug 2: Exact timestamp match creates duplicates (line 136)

The app creates a JobEvent, then `super().save()` fires SimpleHistory's `post_save` signal ~3ms later. The migration matches by `timestamp=rec.history_date` (the HistoricalJob timestamp), misses the app event (3ms earlier), and creates a duplicate.

**Data evidence** (from job 364e4390):
- App events and HistoricalJob records are consistently 3ms apart
- Different status changes for the same job are 6+ seconds apart
- A 1-second window will never contain two different status changes for the same job/event_type

**Fix**: Replace exact timestamp with 1-second window + `delta_after__isnull=True`:

```python
window = timedelta(seconds=1)
existing = JobEvent.objects.filter(
    job_id=job_id,
    event_type=event_type,
    delta_after__isnull=True,
    timestamp__gte=rec.history_date - window,
    timestamp__lte=rec.history_date + window,
).first()
```

`delta_after__isnull=True` ensures:
- Only matches events that haven't been backfilled yet
- Makes the migration idempotent (safe to re-run)
- Avoids matching a previously-backfilled event if re-applied

## File to modify

`apps/job/migrations/0073_backfill_jobevent_status_from_historicaljob.py`

## Test plan

1. Unapply: `python manage.py migrate job 0072`
2. Clean up duplicates from previous run: delete events with "backfilled from history" in description
3. Reapply: `python manage.py migrate job 0073`
4. Verify no duplicates: for a sample job, each status_changed event should appear once (not twice)
5. Verify deltas populated: `JobEvent.objects.filter(event_type='status_changed', delta_after__has_key='status').count()` should equal total `status_changed` count
6. Run WIP report: `WIPService.get_wip_data(date(2025, 12, 31), 'revenue')` should return non-zero jobs and WIP value
