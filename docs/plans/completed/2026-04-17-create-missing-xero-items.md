---
date: 2026-04-17
description: Add --create-missing-calendar to xero --setup
---

## Context

When restoring prod data to a dev environment, the Xero demo org periodically gets reset. The payroll calendar (e.g. "Weekly Testing") no longer exists in the fresh demo org. `xero --setup` fails with a confusing 403 or "not found" error. The fix: a `--create-missing-calendar` flag that creates the calendar if absent, with a clear error message pointing at the calendar when the flag is not set.

## Changes

**File:** `apps/workflow/management/commands/xero.py`

### 1. Imports (already partially added)

```python
import datetime
from xero_python.payrollnz import PayrollNzApi
from xero_python.payrollnz.models import CalendarType, PayRunCalendar
```

### 2. Add argument

```python
parser.add_argument(
    "--create-missing-calendar",
    action="store_true",
    help="Create the payroll calendar in Xero if it does not exist (use when restoring to dev after a demo org reset)",
)
```

### 3. Pass to run_setup

```python
if options["setup"]:
    self.run_setup(create_missing_calendar=options["create_missing_calendar"])
```

### 4. Update run_setup signature

```python
def run_setup(self, create_missing_calendar: bool):
```

### 5. Add create-if-missing step early in run_setup

After saving `tenant_id` (step 3b) and before fetching the shortcode, insert:

```python
if create_missing_calendar:
    self._ensure_payroll_calendar_exists(company.xero_payroll_calendar_name, tenant_id)
```

This guarantees the calendar exists before the normal lookup at step 5 runs.

### 6. New method _ensure_payroll_calendar_exists

```python
def _ensure_payroll_calendar_exists(self, calendar_name: str, tenant_id: str) -> None:
    if not calendar_name:
        return
    calendars = get_payroll_calendars()
    if any(c["name"] == calendar_name for c in calendars):
        return
    self.stdout.write(f"Payroll calendar '{calendar_name}' not found — creating it.")
    today = datetime.date.today()
    period_start = today - datetime.timedelta(days=today.weekday())
    PayrollNzApi(api_client).create_pay_run_calendar(
        xero_tenant_id=tenant_id,
        pay_run_calendar=PayRunCalendar(
            name=calendar_name,
            calendar_type=CalendarType.WEEKLY,
            period_start_date=period_start,
            payment_date=period_start + datetime.timedelta(days=4),
        ),
    )
    self.stdout.write(self.style.SUCCESS(f"Created payroll calendar: {calendar_name}"))
```

### 7. Update calendar lookup error message (step 5)

Replace the existing "not found" error with one that points at the calendar and the flag:

```python
self.stdout.write(self.style.ERROR(
    f"Payroll calendar '{calendar_name}' not found in Xero.\n"
    f"Available calendars: {available}\n"
    f"If restoring to dev after a demo org reset, re-run with --create-missing-calendar."
))
```

## Verification

```
python manage.py xero --setup --create-missing-calendar
```

Should create the calendar and complete setup. Subsequent runs (calendar now exists) should find it without creating a duplicate.
