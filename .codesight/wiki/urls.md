# Urls

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Urls subsystem handles **77 routes** and touches: auth, payment.

## Routes

- `ALL` `/reports/calendar/`
  `apps/accounting/urls.py`
- `ALL` `/reports/job-aging/`
  `apps/accounting/urls.py`
- `ALL` `/reports/job-movement/`
  `apps/accounting/urls.py`
- `ALL` `/reports/payroll-date-range/`
  `apps/accounting/urls.py`
- `ALL` `/reports/payroll-reconciliation/`
  `apps/accounting/urls.py`
- `ALL` `/reports/profit-and-loss/`
  `apps/accounting/urls.py`
- `ALL` `/reports/sales-forecast/`
  `apps/accounting/urls.py`
- `ALL` `/reports/sales-forecast/<str:month>/` params(month)
  `apps/accounting/urls.py`
- `ALL` `/reports/staff-performance-summary/`
  `apps/accounting/urls.py`
- `ALL` `/reports/staff-performance/<uuid:staff_id>/` params(staff_id)
  `apps/accounting/urls.py`
- `ALL` `/reports/rdti-spend/`
  `apps/accounting/urls.py`
- `ALL` `/reports/wip/`
  `apps/accounting/urls.py`
- `ALL` `/staff/all/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/staff/rates/<uuid:staff_id>/` params(staff_id) [auth]
  `apps/accounts/urls.py`
- `ALL` `/me/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/password_change/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/staff/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/staff/<uuid:pk>/` params(pk) [auth]
  `apps/accounts/urls.py`
- `ALL` `/job/completed/`
  `apps/job/urls.py`
- `ALL` `/job/completed/archive`
  `apps/job/urls.py`
- `ALL` `/job/<uuid:job_id>/assignment` params(job_id)
  `apps/job/urls.py`
- `ALL` `/job/<uuid:job_id>/assignment/<uuid:staff_id>` params(job_id, staff_id)
  `apps/job/urls.py`
- `ALL` `/company_defaults/`
  `apps/job/urls.py`
- `ALL` `/jobs/fetch-all/`
  `apps/job/urls.py`
- `ALL` `/jobs/workshop`
  `apps/job/urls.py`
- `ALL` `/workshop/timesheets/`
  `apps/job/urls.py`
- `ALL` `/jobs/<str:job_id>/update-status/` params(job_id)
  `apps/job/urls.py`
- `ALL` `/jobs/<uuid:job_id>/reorder/` params(job_id)
  `apps/job/urls.py`
- `ALL` `/jobs/fetch/<str:status>/` params(status)
  `apps/job/urls.py`
- `ALL` `/jobs/fetch-by-column/<str:column_id>/` params(column_id)
  `apps/job/urls.py`
- `ALL` `/jobs/status-values/`
  `apps/job/urls.py`
- `ALL` `/jobs/advanced-search/`
  `apps/job/urls.py`
- `ALL` `/extract-supplier-price-list/`
  `apps/quoting/urls.py`
- `ALL` `/daily/<str:target_date>/` params(target_date)
  `apps/timesheet/urls.py`
- `ALL` `/staff/<str:staff_id>/daily/<str:target_date>/` params(staff_id, target_date)
  `apps/timesheet/urls.py`
- `ALL` `/weekly/`
  `apps/timesheet/urls.py`
- `ALL` `/jobs/`
  `apps/timesheet/urls.py`
- `ALL` `/payroll/pay-runs/create`
  `apps/timesheet/urls.py`
- `ALL` `/payroll/pay-runs/`
  `apps/timesheet/urls.py`
- `ALL` `/payroll/post-staff-week/`
  `apps/timesheet/urls.py`
- `ALL` `/payroll/post-staff-week/stream/<str:task_id>/` params(task_id)
  `apps/timesheet/urls.py`
- `ALL` `/enums/<str:enum_name>/` params(enum_name) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/authenticate/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/disconnect/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/sync-stream/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/create_invoice/<uuid:job_id>` params(job_id) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/delete_invoice/<uuid:job_id>` params(job_id) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/create_quote/<uuid:job_id>` params(job_id) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/delete_quote/<uuid:job_id>` params(job_id) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/sync-info/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/create_purchase_order/<uuid:purchase_order_id>` params(purchase_order_id) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/delete_purchase_order/<uuid:purchase_order_id>` params(purchase_order_id) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/sync/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero/ping/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/app-errors/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/app-errors/<uuid:pk>/` params(pk) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/rest/app-errors/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero-errors/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/xero-errors/<uuid:pk>/` params(pk) [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/company-defaults/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/company-defaults/upload-logo/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/company-defaults/schema/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/workflow/` [auth, payment, upload]
  `apps/workflow/urls.py`
- `ALL` `/api/`
  `docketworks/urls.py`
- `ALL` `/api/job/`
  `docketworks/urls.py`
- `ALL` `/api/accounts/`
  `docketworks/urls.py`
- `ALL` `/api/timesheets/`
  `docketworks/urls.py`
- `ALL` `/api/quoting/`
  `docketworks/urls.py`
- `ALL` `/api/clients/`
  `docketworks/urls.py`
- `ALL` `/api/purchasing/`
  `docketworks/urls.py`
- `ALL` `/api/accounting/`
  `docketworks/urls.py`
- `ALL` `/api/process/`
  `docketworks/urls.py`
- `ALL` `/api/schema/`
  `docketworks/urls.py`
- `ALL` `/api/docs`
  `docketworks/urls.py`
- `ALL` `ai-providers` [auth, payment, upload] `[inferred]`
  `apps/workflow/urls.py`
- `ALL` `app-errors` [auth, payment, upload] `[inferred]`
  `apps/workflow/urls.py`
- `ALL` `xero-pay-items` [auth, payment, upload] `[inferred]`
  `apps/workflow/urls.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/accounting/urls.py`
- `apps/accounts/urls.py`
- `apps/job/urls.py`
- `apps/quoting/urls.py`
- `apps/timesheet/urls.py`
- `apps/workflow/urls.py`
- `docketworks/urls.py`

---
_Back to [overview.md](./overview.md)_