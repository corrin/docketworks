# WIP Report

## Context

A WIP (Work In Progress) report was prototyped directly in production as a CLI script. The business logic works — it calculates uninvoiced value on active jobs with two valuation methods (revenue/cost), filters by date, and separates archived jobs as a data-quality warning.

We need to turn this into a proper feature: backend API endpoint + frontend report page, following the same patterns as the existing Job Aging and Staff Performance reports.

## Step 1: Backend — WIP Service

**Create:** `apps/accounting/services/wip_service.py`

Extract the business logic from the prod script into a `WIPService` class with static methods, following the `JobAgingService` pattern in `apps/accounting/services/core.py:773`.

- `get_wip_data(report_date: date, method: str) -> dict` — main entry point
- `_aggregate_job(job: Job, report_date: date, method: str) -> dict | None` — per-job calculation (from prod script)
- Returns dict with: `jobs` (active WIP rows), `archived_jobs` (excluded rows), `summary` (totals, breakdown by status)
- Error handling: `persist_app_error` + `AlreadyLoggedException` pattern (see `core.py:27`)

Key logic to preserve from the prod script:
- Filter: `fully_invoiced=False`, `rejected_flag=False`, exclude draft/awaiting_approval, exclude null `latest_actual`
- CostLine aggregation by kind (time/material/adjust) using `accounting_date__lte=report_date`
- Invoice deduction: sum `total_excl_tax` where status in DRAFT/SUBMITTED/AUTHORISED/PAID
- Two valuation methods: revenue (quantity × unit_rev) vs cost (quantity × unit_cost)
- Net WIP = gross WIP - invoiced

## Step 2: Backend — Serializers

**Edit:** `apps/accounting/serializers/core.py` (or create `wip_serializers.py` if core.py is getting large)

- `WIPQuerySerializer` — validates `date` (YYYY-MM-DD, defaults to today) and `method` (revenue|cost, defaults to revenue)
- `WIPJobSerializer` — per-job row: job_number, name, client, status, time_cost, time_rev, material_cost, material_rev, adjust_cost, adjust_rev, total_cost, total_rev, invoiced, gross_wip, net_wip
- `WIPStatusBreakdownSerializer` — status, count, net_wip
- `WIPSummarySerializer` — total_gross, total_invoiced, total_net, job_count, by_status (many)
- `WIPResponseSerializer` — jobs (many), archived_jobs (many), summary, report_date, method

## Step 3: Backend — API View

**Create:** `apps/accounting/views/wip_view.py`

`WIPReportAPIView(APIView)` with a `get()` method, following `job_aging_view.py` exactly:
- Validate query params with `WIPQuerySerializer`
- Call `WIPService.get_wip_data(date, method)`
- Serialize response with `WIPResponseSerializer`
- Error handling with `persist_app_error` + `extract_request_context`

**Edit:** `apps/accounting/urls.py` — add:
```python
path("reports/wip/", WIPReportAPIView.as_view(), name="api_wip_report"),
```

Final endpoint: `GET /api/accounting/reports/wip/?date=2026-03-31&method=revenue`

**Run:** `python scripts/update_init.py` after adding new files.

## Step 4: Frontend — Service + View

**Delegate to frontend subagent** per CLAUDE.md rules (frontend has its own conventions).

After backend is deployed, run `npm run update-schema && npm run gen:api` to get types, then:
- Create `frontend/src/services/wip-report.service.ts`
- Create `frontend/src/views/WIPReportView.vue` — table of jobs with summary totals, date picker, method toggle
- Add route in `frontend/src/router/index.ts`
- Add nav link in `frontend/src/components/AppNavbar.vue`

## Files to modify/create

| Action | File |
|--------|------|
| Create | `apps/accounting/services/wip_service.py` |
| Create | `apps/accounting/serializers/wip_serializers.py` |
| Create | `apps/accounting/views/wip_view.py` |
| Edit | `apps/accounting/urls.py` |
| Run | `python scripts/update_init.py` |
| Create | `frontend/src/services/wip-report.service.ts` |
| Create | `frontend/src/views/WIPReportView.vue` |
| Edit | `frontend/src/router/index.ts` |
| Edit | `frontend/src/components/AppNavbar.vue` |

## Reference files

- `apps/accounting/views/job_aging_view.py` — view pattern
- `apps/accounting/services/core.py:773` — JobAgingService pattern
- `apps/accounting/serializers/core.py:170` — serializer pattern
- `apps/workflow/services/error_persistence.py` — persist_app_error
- `apps/workflow/exceptions.py` — AlreadyLoggedException

## Verification

```bash
# Backend
python manage.py test apps.accounting -k wip  # if tests added
curl /api/accounting/reports/wip/
curl /api/accounting/reports/wip/?date=2026-03-31&method=cost

# Frontend
npm run update-schema && npm run gen:api
npm run dev  # navigate to /reports/wip
```
