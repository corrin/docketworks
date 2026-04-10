# Fix WIP Report Historical Job State

## Context

The WIP report is supposed to show work-in-progress as at a given date. When you pick a past date, it should show what jobs **were** in progress on that date and what their WIP was. Currently it's broken in two ways:

1. **Job filtering uses current state, not historical state** — The base queryset filters on `fully_invoiced=False`, `rejected_flag=False`, and excludes `status__in=["draft", "awaiting_approval"]`. These are all **current** field values. A job that was `in_progress` on the report date but is now `fully_invoiced=True` or `archived` gets silently excluded from the historical report.

2. **Invoice deduction ignores dates** — The invoice query sums ALL invoices for a job regardless of when they were issued. For a historical report date, only invoices dated on or before the report date should be deducted.

## Fix

**File:** `apps/accounting/services/wip_service.py`

### Step 1: Widen the base queryset

Remove the current-state filters (`fully_invoiced`, `rejected_flag`, `status`) from the base queryset. Instead, select all jobs that have a `latest_actual` cost set (i.e. have ever had actual cost activity).

### Step 2: Use SimpleHistory to get historical job state

For each job, use `job.history.filter(history_date__lte=report_date).order_by('-history_date').first()` to get the job's state as of the report date. Use the historical record's `status`, `fully_invoiced`, and `rejected_flag` to decide inclusion/exclusion:

- Skip if historical `status` is in `NO_WORK_STATUSES` (draft, awaiting_approval)
- Skip if historical `fully_invoiced` is True
- Skip if historical `rejected_flag` is True
- Route to `archived_jobs` if historical `status` is "archived"

If no history record exists before the report date (job was created after), skip the job entirely.

### Step 3: Filter invoices by date

Add `date__lte=report_date` to the invoice query in `_aggregate_job`:

```python
invoiced = Invoice.objects.filter(
    job=job,
    status__in=VALID_INVOICE_STATUSES,
    date__lte=report_date,
).aggregate(total=Sum("total_excl_tax"))["total"] or Decimal("0")
```

### Step 4: Use historical status for the row

The `status` field in the returned row should use the historical status, not `job.status`. Pass the historical record into `_aggregate_job` or return the historical status from the caller.

## Key files

- `apps/accounting/services/wip_service.py` — the service with the bugs
- `apps/job/models/job.py` — Job model with `HistoricalRecords`
- `apps/accounting/models/invoice.py` — Invoice model with `date` field

## Verification

1. Run existing WIP tests: `tox -e test -- apps/accounting/tests/ -k wip`
2. Manual check: pick a date in the past where a now-archived/fully-invoiced job was active — confirm it appears in the historical report
3. Confirm today's date still produces correct results (historical state = current state for today)
