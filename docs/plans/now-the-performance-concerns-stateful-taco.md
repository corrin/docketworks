# Sales Pipeline Report — performance: move the worst offenders to SQL?

## Context

Two Copilot review comments on #162 flagged the Sales Pipeline service as having hot paths that do Python-side work which could move to SQL:

1. `apps/accounting/services/sales_pipeline_service.py:121-131` (`_fetch_events`) — loads *all* relevant JobEvent rows up to `end_date`, groups in Python.
2. `apps/accounting/services/sales_pipeline_service.py:726-806` (`_build_trend_week`) — called `trend_weeks` times (default 13); each call walks every job's event list again. Overall `O(weeks × jobs × events)`.

The user's question for this plan: *how hard would it actually be to move the worst of it into SQL?*

**Real scale today (dev DB, which mirrors prod):**

| Metric                                                   | Count   |
| -------------------------------------------------------- | ------- |
| JobEvent rows across the 4 relevant event types          | **3,314** |
| Distinct jobs that have any of those events              | 1,097   |
| Total Job rows                                            | 1,883   |
| Total CostSet rows                                        | 5,649   |
| Date range covered by the event stream                    | 2025-09-13 → 2026-04-22 (7 months) |

**Current DB cost** (EXPLAIN ANALYZE of `_fetch_events`):

```
Execution Time: 4.502 ms — Bitmap Index Scan on jobevent_type_timestamp_idx
```

The existing composite index `(event_type, -timestamp)` at `apps/job/models/job_event.py:208-220` already serves this query. Python-side grouping of 3,314 rows is low-single-digit milliseconds on top. **End-to-end report latency is dominated by the CostSet join, not the event loop.** The "hotspot" is hypothetical — real at maybe 10–50× current scale.

So the honest answer to "how hard to move it into SQL" is: **not hard, but the payoff is negligible until the data gets bigger.** The plan below proposes a *tiered* response with an honest threshold for when each tier pays off.

## Recommendation

Do Tier 1 only. Document Tier 2/3 as *recipes* so when scale justifies them the design is already agreed. Don't rewrite Sales Pipeline today for 4.5ms of DB time.

---

## Tier 1 — Cheap narrowing (≈1 hour, do now)

**Goal:** Stop fetching events older than any section needs. Currently `_fetch_events` fetches `timestamp__lte=end_date` with no lower bound, so seven months of history is loaded even when the user requests a one-week window.

**Concrete changes:**

- Compute `fetch_start_dt` = min of:
  - `start_date` (scoreboard / funnel / velocity period start),
  - `end_week_start - timedelta(weeks=trend_weeks - 1)` (trend window start),
  - the earliest `job_created` timestamp we still need for snapshot replay of *currently* draft/awaiting_approval jobs.
  The last one is the tricky part — snapshot-as-of-end_date needs to replay back to `job_created`, which may predate the reporting window. Resolve this by fetching creation anchors *unbounded* for pipeline-stage jobs specifically, then fetching in-window events for everyone. Two queries instead of one, but each is tighter.
- Add `.only("id", "job_id", "timestamp", "event_type", "delta_after", "delta_before")` to avoid pulling `description`, `detail`, `schema_version`, etc. that the service never reads.
- Add `.iterator(chunk_size=2000)` when materialising into `events_by_job`, so memory stays bounded even as the table grows.
- Sanity cap: emit a warning (via existing warning machinery) if `events_by_job` exceeds e.g. 50k rows so silent O(n²) regressions are visible.

**Files touched:** `apps/accounting/services/sales_pipeline_service.py` only.

**Risk:** Low. Semantics unchanged; existing tests cover behaviour. Add one new test asserting the narrowed fetch still produces correct historical snapshot for a job whose `job_created` precedes the reporting window.

---

## Tier 2 — SQL aggregation for flat sections (~1 day, hold until trigger)

**Trigger:** event count > 30k OR sales pipeline endpoint p95 > 500ms in Grafana. Not before.

**Scope:** scoreboard, velocity, funnel. Snapshot and trend stay Python-side because they involve historical state replay, which is genuinely harder in SQL.

**Pattern to follow:** `apps/accounting/services/rdti_spend_service.py:30-70` — `.values() → .annotate()` with `Coalesce(Sum(F(...)))`. Already proven in this codebase.

**JSON extraction:** use `KeyTextTransform("status", "delta_after")` exactly as `apps/accounting/services/core.py:167-175` does for CostLine meta — battle-tested here.

**Query shape for scoreboard** (illustrative):

```python
from django.db.models.functions import KeyTextTransform

qualifying = (
    JobEvent.objects.annotate(
        after_status=KeyTextTransform("status", "delta_after"),
    )
    .filter(
        timestamp__range=(period_start, period_end),
        job__isnull=False,
    )
    .filter(
        Q(event_type="status_changed", after_status__in=APPROVED_STATUSES)
        | Q(event_type="quote_accepted"),
    )
    .values("job_id")
    .annotate(first_ts=Min("timestamp"))
)
# Join to Job + latest_quote for hours aggregation via Subquery/OuterRef.
```

Velocity and funnel follow the same mould — group by job_id, aggregate Min/Max of timestamp per event_type, then one Python pass to compute medians / bucket counts from the row-per-job result set. Critically: **no cross join of weeks × jobs**.

**Explicitly not doing:** window functions. Grep confirmed `apps/` uses zero `Window()` / `RowNumber()` today. Adding them would be a one-off pattern that reviewers won't recognise. Staying inside the `.values().annotate()` / `Subquery(OuterRef(...))` dialect keeps the rewrite legible.

---

## Tier 3 — Full trend rewrite (probably never)

Trend is the genuine O(weeks × jobs × events) loop. But:

- At 13 weeks × 1,097 jobs × ~3 events/job = **~43k iterations**. Tens of milliseconds in Python.
- A SQL rewrite needs per-week pipeline-hours-at-week-end, which is per-week status replay — the only clean SQL form is a CTE with `generate_series(week_start, week_end, interval '1 week')` cross-joined to `DISTINCT ON (job_id, week_bucket) ORDER BY job_id, week_bucket, timestamp DESC`. That's a different SQL idiom from the rest of the codebase.
- The cost/benefit is bad until events grow ~100×.

**Plan:** don't do this. If it ever matters, revisit as a separate ADR because the idiom would set a precedent for other reports.

---

## Verification

Tier 1 is the only tier this plan authorises; verify with:

```
DJANGO_SETTINGS_MODULE=docketworks.settings_test python manage.py test apps.accounting.tests --keepdb
```

- 28 existing tests must pass unchanged.
- Add one new `SnapshotTests.test_narrowed_fetch_preserves_historical_replay` — a job created three years before `start_date`, transitions inside the reporting window, must still appear correctly in the snapshot.
- Confirm a single-week report (`start_date == end_date - 6 days`) no longer issues a query that returns the full 7-month event history. Capture with `django.test.utils.CaptureQueriesContext` in a new API-level test.

## Files

- `apps/accounting/services/sales_pipeline_service.py` — Tier 1 changes live entirely here.
- `apps/accounting/tests/test_sales_pipeline_service.py` — add the one historical-replay test.
- `apps/accounting/tests/test_sales_pipeline_api.py` — add the query-count test.
- No migration needed; existing `jobevent_type_timestamp_idx` already serves the narrowed query.

## Reference index

- Reusable aggregation template: `apps/accounting/services/rdti_spend_service.py:30-70`
- JSON-in-ORM template: `apps/accounting/services/core.py:167-175` (`KeyTextTransform`)
- JobEvent model + indexes: `apps/job/models/job_event.py:12-78` (fields), `:208-220` (indexes)
- Current hot paths: `apps/accounting/services/sales_pipeline_service.py:121-131`, `:726-806`
- Copilot review threads (held for planning): PR #162 comments `3132984843` (fetch-all) and `3132984872` (trend O(wjx))
