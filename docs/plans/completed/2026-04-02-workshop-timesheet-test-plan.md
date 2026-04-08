# Backend permission test: workshop timesheet entry for normal users

## Context

The workshop timesheet API (`/api/job/workshop/timesheets/`) has zero backend test coverage. Need to verify that normal (non-admin) staff users can create timesheet entries — the permission is `IsAuthenticated` so any logged-in user should work, but this has never been tested.

## Changes

**New file:** `apps/job/tests/test_workshop_timesheet_api.py`

Using `BaseAPITestCase` (from `apps/testing`), create a test class that:

1. Sets up a non-admin Staff user and a Job
2. **test_normal_user_can_create_entry** — POST to `/api/job/workshop/timesheets/` as the normal user, assert 201
3. **test_normal_user_can_list_entries** — GET as normal user, assert 200 and entry appears
4. **test_normal_user_can_update_own_entry** — PATCH own entry, assert 200
5. **test_normal_user_can_delete_own_entry** — DELETE own entry, assert 204
6. **test_unauthenticated_rejected** — request without auth, assert 401/403
7. **test_cannot_update_other_staff_entry** — PATCH entry owned by different staff, assert 403

### Key files to reference
- View: `apps/job/views/workshop_view.py` — `WorkshopTimesheetView`
- Service: `apps/job/services/workshop_service.py` — `WorkshopTimesheetService`
- Serializers: `apps/timesheet/serializers/modern_timesheet_serializers.py`
- Test base: `apps/testing.py` — `BaseAPITestCase`
- Existing pattern: `apps/job/tests/test_costline_schema_validation.py`

## Verification

```bash
python manage.py test apps.job.tests.test_workshop_timesheet_api -v2
```
