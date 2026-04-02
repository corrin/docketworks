# Timesheet Superuser Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate all timesheet management views behind a `CanManageTimesheets` permission (aliasing `is_superuser`) using a shared base view class, and hide the Timesheets menu from non-superusers in the frontend.

**Architecture:** Add `CanManageTimesheets` permission class in `apps/accounts/permissions.py`. Create `TimesheetBaseView(APIView)` in `apps/timesheet/views/base.py` that sets `permission_classes = [IsAuthenticated, CanManageTimesheets]`. All 10 class-based timesheet views inherit from it. The `stream_payroll_post` function gets a `@require_superuser` decorator. Frontend hides the Timesheets menu and adds `requiresSuperUser` route meta.

**Tech Stack:** Django REST Framework, Vue 3, vue-router

---

### Task 1: Add `CanManageTimesheets` Permission Class

**Files:**
- Modify: `apps/accounts/permissions.py`
- Create: `apps/timesheet/tests/__init__.py`
- Create: `apps/timesheet/tests/test_permissions.py`

- [ ] **Step 1: Create test directory and write failing tests**

Create `apps/timesheet/tests/__init__.py` (empty file) and `apps/timesheet/tests/test_permissions.py`:

```python
"""Tests for timesheet permission gating."""

from django.test import RequestFactory
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase


class TimesheetPermissionTests(BaseTestCase):
    """Test that timesheet endpoints require superuser access."""

    def setUp(self):
        self.factory = RequestFactory()
        self.client_api = APIClient()

        self.superuser = Staff.objects.create_user(
            email="super@example.com",
            password="testpass123",
            first_name="Super",
            last_name="User",
            is_superuser=True,
            is_office_staff=True,
        )
        self.normal_user = Staff.objects.create_user(
            email="normal@example.com",
            password="testpass123",
            first_name="Normal",
            last_name="User",
            is_superuser=False,
            is_office_staff=True,
        )

    def test_weekly_timesheet_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/weekly/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_weekly_timesheet_allowed_for_superuser(self):
        self.client_api.force_authenticate(user=self.superuser)
        response = self.client_api.get("/api/timesheets/weekly/")
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_daily_summary_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/daily/2026-04-01/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_daily_detail_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get(
            f"/api/timesheets/staff/{self.superuser.id}/daily/2026-04-01/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_list_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/staff/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_jobs_list_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get("/api/timesheets/jobs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_payroll_endpoints_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        # Post week to Xero
        response = self.client_api.post("/api/timesheets/payroll/post-staff-week/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Create pay run
        response = self.client_api.post("/api/timesheets/payroll/pay-runs/create")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Refresh pay runs
        response = self.client_api.post("/api/timesheets/payroll/pay-runs/refresh")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # List pay runs
        response = self.client_api.get("/api/timesheets/payroll/pay-runs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_stream_payroll_blocked_for_normal_user(self):
        self.client_api.force_authenticate(user=self.normal_user)
        response = self.client_api.get(
            "/api/timesheets/payroll/post-staff-week/stream/fake-task-id/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/corrin/src/docketworks && python -m pytest apps/timesheet/tests/test_permissions.py -v`

Expected: All tests FAIL (views currently return 200, not 403).

- [ ] **Step 3: Add `CanManageTimesheets` to permissions.py**

Add to `apps/accounts/permissions.py` after the `IsStaff` class:

```python
class CanManageTimesheets(BasePermission):
    """Gate for timesheet management — viewing/editing other staff pay data."""

    def has_permission(self, request: HttpRequest, view: "APIView") -> bool:
        return bool(request.user and request.user.is_superuser)
```

- [ ] **Step 4: Regenerate `__init__.py` files**

Run: `cd /home/corrin/src/docketworks && python scripts/update_init.py`

- [ ] **Step 5: Commit permission class**

```bash
git add apps/accounts/permissions.py apps/timesheet/tests/
git commit -m "feat: add CanManageTimesheets permission class and tests"
```

---

### Task 2: Create `TimesheetBaseView` and Migrate Views

**Files:**
- Create: `apps/timesheet/views/base.py`
- Modify: `apps/timesheet/views/api.py`
- Modify: `apps/timesheet/api/daily_timesheet_views.py`

- [ ] **Step 1: Create `apps/timesheet/views/base.py`**

```python
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.permissions import CanManageTimesheets


class TimesheetBaseView(APIView):
    """Base view for all timesheet endpoints. Requires superuser access."""

    permission_classes = [IsAuthenticated, CanManageTimesheets]
```

- [ ] **Step 2: Update `apps/timesheet/views/api.py` — change all 8 class-based views**

Replace the `APIView` import usage. In the imports section, add:

```python
from apps.timesheet.views.base import TimesheetBaseView
```

Change each view's parent class:

| View | Old | New |
|------|-----|-----|
| `StaffListAPIView` | `APIView` | `TimesheetBaseView` |
| `JobsAPIView` | `APIView` | `TimesheetBaseView` |
| `DailyTimesheetAPIView` | `APIView` | `TimesheetBaseView` |
| `WeeklyTimesheetAPIView` | `TimesheetResponseMixin, APIView` | `TimesheetResponseMixin, TimesheetBaseView` |
| `CreatePayRunAPIView` | `APIView` | `TimesheetBaseView` |
| `PayRunListAPIView` | `APIView` | `TimesheetBaseView` |
| `RefreshPayRunsAPIView` | `APIView` | `TimesheetBaseView` |
| `PostWeekToXeroPayrollAPIView` | `APIView` | `TimesheetBaseView` |

Remove `permission_classes = [IsAuthenticated]` from each view (inherited from base).

Keep the `from rest_framework.views import APIView` import — it's still used by `TimesheetResponseMixin` and `build_internal_error_response`.

- [ ] **Step 3: Update `apps/timesheet/api/daily_timesheet_views.py` — change 2 views**

Add import:

```python
from apps.timesheet.views.base import TimesheetBaseView
```

Change each view's parent class:

| View | Old | New |
|------|-----|-----|
| `DailyTimesheetSummaryAPIView` | `APIView` | `TimesheetBaseView` |
| `StaffDailyDetailAPIView` | `APIView` | `TimesheetBaseView` |

Remove `permission_classes = [IsAuthenticated]` from each view.

The `from rest_framework.views import APIView` import can be removed from this file as nothing else uses it.

- [ ] **Step 4: Gate `stream_payroll_post` function**

In `apps/timesheet/views/api.py`, add a superuser check to the `stream_payroll_post` function. After the existing authentication guard (line 737-739), add:

```python
    # Superuser check - timesheet data is sensitive
    if not request.user.is_superuser:
        return JsonResponse(
            {"detail": "You do not have permission to perform this action."},
            status=403,
        )
```

This goes right after the `guard = _require_authenticated_api(request)` / `if guard: return guard` block.

- [ ] **Step 5: Regenerate `__init__.py` files**

Run: `cd /home/corrin/src/docketworks && python scripts/update_init.py`

- [ ] **Step 6: Run permission tests to verify they pass**

Run: `cd /home/corrin/src/docketworks && python -m pytest apps/timesheet/tests/test_permissions.py -v`

Expected: ALL tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/timesheet/views/base.py apps/timesheet/views/api.py apps/timesheet/api/daily_timesheet_views.py
git commit -m "feat: gate timesheet views behind TimesheetBaseView with CanManageTimesheets"
```

---

### Task 3: Frontend — Hide Timesheets Menu and Gate Routes

**Files:**
- Modify: `frontend/src/components/AppNavbar.vue`
- Modify: `frontend/src/router/index.ts`

- [ ] **Step 1: Gate the Timesheets dropdown in AppNavbar.vue**

In the desktop navigation, change the Timesheets dropdown condition from:

```vue
<div v-if="userInfo.is_office_staff">
```

to:

```vue
<div v-if="userInfo.is_superuser">
```

This is the block containing `toggleDropdown('timesheets')` with the Calendar icon and "Timesheets" label (around line 173 in AppNavbar.vue).

Do the same for the mobile menu Timesheets section — find the mobile timesheet expansion block and gate it with `userInfo.is_superuser`.

**Important:** The "My Time" link for workshop staff (`v-if="!userInfo.is_office_staff"`) must NOT be changed — it's for individual staff viewing their own time and is not sensitive.

- [ ] **Step 2: Add `requiresSuperUser` meta to timesheet routes**

In `frontend/src/router/index.ts`, add `requiresSuperUser: true` to the meta of these routes:

- `timesheet-entry` (`/timesheets/entry`)
- `timesheet-daily` (`/timesheets/daily`)
- `WeeklyTimesheet` (`/timesheets/weekly`)
- The `/timesheets` redirect

Do NOT add it to `timesheet-my-time` (`/timesheets/my-time`) — that's the workshop staff personal timesheet.

Example for the entry route:

```typescript
{
  path: '/timesheets/entry',
  name: 'timesheet-entry',
  component: () => import('@/views/TimesheetEntryView.vue'),
  meta: {
    requiresAuth: true,
    requiresSuperUser: true,
    title: 'Timesheet Entry - DocketWorks',
  },
},
```

The router guard for `requiresSuperUser` already exists (checks `authStore.user?.is_superuser` and redirects with a toast error). No guard changes needed.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd /home/corrin/src/docketworks/frontend && npm run type-check`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
cd /home/corrin/src/docketworks
git add frontend/src/components/AppNavbar.vue frontend/src/router/index.ts
git commit -m "feat: hide Timesheets menu and gate routes for non-superusers"
```

---

### Task 4: Clean Up Dead Code

**Files:**
- Modify: `apps/timesheet/views/api.py`

- [ ] **Step 1: Remove `DailyTimesheetAPIView` dead code**

`DailyTimesheetAPIView` (around line 238-389 in `apps/timesheet/views/api.py`) is not imported in `urls.py` — the URL conf uses `DailyTimesheetSummaryAPIView` and `StaffDailyDetailAPIView` from `api/daily_timesheet_views.py` instead. Remove the entire `DailyTimesheetAPIView` class.

Also remove `_is_weekend_enabled` from `TimesheetResponseMixin` — it's only called by the dead `DailyTimesheetAPIView` code and `WeeklyTimesheetAPIView.build_timesheet_response`. Wait — `build_timesheet_response` calls `self._is_weekend_enabled()` at line 411. Keep `TimesheetResponseMixin._is_weekend_enabled`.

So: remove only `DailyTimesheetAPIView` (lines 238-389).

- [ ] **Step 2: Verify nothing breaks**

Run: `cd /home/corrin/src/docketworks && python -m pytest apps/timesheet/tests/test_permissions.py -v`

Expected: ALL tests still PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/timesheet/views/api.py
git commit -m "chore: remove dead DailyTimesheetAPIView (replaced by daily_timesheet_views.py)"
```
