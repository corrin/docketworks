# Timesheet Superuser Gate — Design Spec

**Date:** 2026-04-02
**Status:** Design

## Problem

Timesheet views expose sensitive pay data (how much staff are paid, hours worked at what rates). Currently all 10 timesheet API views independently set `permission_classes = [IsAuthenticated]`, meaning any authenticated user can see what other staff members earn. An emergency production fix added `IsSuperUser` to each view individually — this works but is fragile (10 places to maintain, easy to miss new views).

## Business Rule

**Views exposing what other staff earn MUST require superuser access.** Everything else: gate or not, whichever is simplest to maintain. Since a single base class is simplest, all timesheet views get gated by default.

The `is_superuser` flag already identifies the right people (Cindy/Corrin). This won't change — if someone is trusted to see other people's pay, they're trusted fully.

**Don't show people things they can't access.** The Timesheets menu must be hidden entirely for non-superusers, not just disabled or gated on click.

## Design

### 1. `CanManageTimesheets` Permission Class

A named permission in `apps/accounts/permissions.py` that checks `is_superuser`. The alias communicates business intent rather than implementation detail.

```python
class CanManageTimesheets(BasePermission):
    """Gate for timesheet management — viewing/editing other staff pay data."""
    def has_permission(self, request, view):
        return request.user.is_superuser
```

### 2. `TimesheetBaseView` Base Class

New base class in `apps/timesheet/views/base.py`:

```python
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from apps.accounts.permissions import CanManageTimesheets

class TimesheetBaseView(APIView):
    permission_classes = [IsAuthenticated, CanManageTimesheets]
```

All 10 timesheet view classes change their parent from `APIView` to `TimesheetBaseView`. No other changes to the views — method signatures, logic, and URLs stay identical.

`WeeklyTimesheetAPIView` currently inherits from `TimesheetResponseMixin, APIView`. It becomes `TimesheetResponseMixin, TimesheetBaseView`.

### 3. SSE Function (`stream_payroll_post`)

This is a plain function, not a class-based view. Options:

- **Convert to class-based view** inheriting `TimesheetBaseView` — cleanest, consistent with the rest
- **Add a `@can_manage_timesheets` decorator** — less churn

Recommend converting to a class-based view for consistency unless the SSE streaming pattern makes that awkward. Decide during implementation.

### 4. Frontend Changes

Two changes (per existing spec at `docs/plans/2026-04-02-timesheet-menu-superuser-gate.md`):

1. **Navigation:** Remove the Timesheets menu entirely when `is_superuser` is false — don't show people things they can't access. (`is_superuser` already available from `/accounts/me/`)
2. **Route guard:** Add `requiresSuperUser` meta to timesheet routes so direct URL access redirects away

### 5. Files Changed

| File | Change |
|------|--------|
| `apps/accounts/permissions.py` | Add `CanManageTimesheets` |
| `apps/timesheet/views/base.py` | New file: `TimesheetBaseView` |
| `apps/timesheet/views/api.py` | 8 views: `APIView` → `TimesheetBaseView` |
| `apps/timesheet/api/daily_timesheet_views.py` | 2 views: `APIView` → `TimesheetBaseView` |
| `apps/timesheet/views/api.py` | `stream_payroll_post`: gate via decorator or convert to CBV |
| Frontend navigation component | Gate Timesheets menu on `is_superuser` |
| Frontend router | Add `requiresSuperUser` route meta |

### 6. What This Does NOT Change

- No model changes, no migrations
- No changes to the mobile "my own timesheet" endpoints (those are separate and not sensitive)
- No new API endpoints
- `IsStaff` permission class unchanged
- URL routing unchanged
