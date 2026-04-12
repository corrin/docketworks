# Auth

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Auth subsystem handles **6 routes** and touches: auth, payment.

## Routes

- `ALL` `/token/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/token/refresh/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/token/verify/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/logout/` [auth]
  `apps/accounts/urls.py`
- `ALL` `/payroll/pay-runs/refresh`
  `apps/timesheet/urls.py`
- `ALL` `/xero/oauth/callback/` [auth, payment, upload]
  `apps/workflow/urls.py`

## Middleware

- **auth** (auth) — `apps/workflow/api/xero/auth.py`
- **authentication** (auth) — `apps/workflow/authentication.py`
- **middleware** (auth) — `apps/workflow/middleware.py`
- **auth** (auth) — `frontend/src/stores/auth.ts`
- **auth** (auth) — `frontend/tests/fixtures/auth.ts`

## Source Files

Read these before implementing or modifying this subsystem:
- `apps/accounts/urls.py`
- `apps/timesheet/urls.py`
- `apps/workflow/urls.py`

---
_Back to [overview.md](./overview.md)_