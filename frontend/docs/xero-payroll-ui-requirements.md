# Xero Payroll UI Requirements

**For:** Frontend Vue.js Implementation
**Backend Branch:** `feature/xero-payroll` (backend complete, REST API not yet implemented)
**Date:** 2025-11-04

## Overview

Office manager needs UI to:

1. Create Draft pay runs for weekly periods
2. Post staff timesheets to existing pay runs
3. View posting results and handle errors

## User Workflow

**Weekly Process:**

1. **Monday-Friday:** Office manager enters daily timesheets as normal (no change to existing timesheet entry UI)
2. **End of Week (or before):**
   - Office manager navigates to "Weekly Timesheets" page
   - Creates pay run for the week (if not already created)
   - Posts hours to Xero for each staff member
   - Reviews results
3. **In Xero:** Office manager reviews pay run, approves, posts (locks it)
4. **Next Week:** Cannot modify previous week once Posted in Xero

## Page: Weekly Timesheets

### Location

Existing page: Weekly timesheets view (where office manager reviews entered hours)

### New UI Elements Required

#### 1. Pay Run Management Section (Top of Page)

**Display Current Week Info:**

```
Week: Nov 10-16, 2025 (Mon-Sun)
Payment Date: Nov 19, 2025 (Wed)
Pay Run Status: [Draft | Posted | Not Created]
```

**Button: "Create Pay Run for This Week"**

- Visible when: Pay run doesn't exist for current week
- Hidden when: Pay run already exists
- Action: Calls `POST /api/payroll/create-pay-run/`
  - Request: `{ "week_start_date": "2025-11-10" }` (Monday)
  - Response: `{ "id": "uuid", "xero_id": "uuid", "status": "Draft", "payment_date": "2025-11-19" }`
- On success: Show success message, hide button, show "Pay run created" status
- On error:
  - If "only be one draft pay run": Tell user "A draft pay run already exists for a different week. Please post or delete it in Xero first."
  - Other errors: Display error message from backend

**Pay Run Status Indicator:**

- **Draft** (green): "✓ Pay run ready for posting"
- **Posted** (blue/locked): "🔒 Pay run locked (already paid)"
- **Not Created** (gray): "Pay run not created yet"

#### 2. Staff Timesheet Posting Section

**For each staff member with hours this week:**

```
┌─────────────────────────────────────────────────┐
│ Tonya Harris                                    │
│ Work: 22h | Other Leave: 3h | Annual/Sick: 3h  │
│ Unpaid: 12h (not posted)                       │
│                                                  │
│ Status: Not posted | Last posted: Never        │
│ [Post to Xero]                                  │
└─────────────────────────────────────────────────┘
```

**Button: "Post to Xero"** (for each staff member)

- Disabled when:
  - Pay run not created (show tooltip: "Create pay run first")
  - Pay run status is "Posted" (show tooltip: "This week is locked")
  - Currently posting (loading state)
- Action: Calls `POST /api/payroll/post-staff-week/`
  - Request: `{ "staff_id": "uuid", "week_start_date": "2025-11-10" }`
  - Response:
    ```json
    {
      "success": true,
      "xero_timesheet_id": "uuid",
      "xero_leave_ids": ["uuid1", "uuid2"],
      "entries_posted": 22,
      "work_hours": "22.00",
      "other_leave_hours": "3.00",
      "annual_sick_hours": "3.00",
      "unpaid_hours": "12.00",
      "errors": []
    }
    ```
- On success:
  - Update status to "Posted to Xero ✓"
  - Show breakdown in collapsed detail section
  - Change button text to "Re-post to Xero" (in case of edits)
- On error:
  - If "already Posted": Show "This week is locked and cannot be modified"
  - If "No pay run found": Show "Please create a pay run first"
  - Other errors: Display `errors` array from response

**Loading State:**

- Button shows spinner: "Posting..."
- Disable button during posting

**Success State:**

```
┌─────────────────────────────────────────────────┐
│ Tonya Harris                               ✓    │
│ Work: 22h | Other Leave: 3h | Annual/Sick: 3h  │
│ Unpaid: 12h (not posted)                       │
│                                                  │
│ Status: Posted to Xero ✓                       │
│ Last posted: 2 minutes ago                     │
│ [Re-post to Xero]  [View Details ▼]            │
│                                                  │
│ Details (expanded):                             │
│   • Timesheet ID: 0184d33a...                  │
│   • Leave records: 2 created                   │
│   • 40 entries processed                       │
└─────────────────────────────────────────────────┘
```

#### 3. Bulk Actions (Optional Enhancement)

**Button: "Post All Staff to Xero"**

- Posts all staff with hours for this week sequentially
- Shows progress: "Posting 3 of 10 staff..."
- Reports summary at end

## REST API Endpoints Required

### 1. Create Pay Run

```
POST /api/payroll/create-pay-run/

Request:
{
  "week_start_date": "2025-11-10"  // Must be Monday
}

Response:
{
  "id": "e1c308ab-da45-407f-b1ec-2433e0c6d2fa",
  "xero_id": "a2b3c4d5-e6f7-8901-abcd-ef0123456789",
  "status": "Draft",
  "period_start_date": "2025-11-10",
  "period_end_date": "2025-11-16",
  "payment_date": "2025-11-19"
}

Errors:
- 400: "week_start_date must be a Monday"
- 409: "There can only be one draft pay run per a calendar"
- 500: Xero API errors
```

### 2. Get Pay Run Status

```
GET /api/payroll/pay-run-status/?week_start_date=2025-11-10

Response:
{
  "exists": true,
  "id": "uuid",
  "xero_id": "uuid",
  "status": "Draft",  // or "Posted"
  "period_start_date": "2025-11-10",
  "period_end_date": "2025-11-16",
  "payment_date": "2025-11-19"
}

Or:
{
  "exists": false
}
```

### 3. Post Staff Week

```
POST /api/payroll/post-staff-week/

Request:
{
  "staff_id": "4591546b-8256-4567-89ab-ae35f58e9f43",
  "week_start_date": "2025-11-10"  // Must be Monday
}

Response:
{
  "success": true,
  "xero_timesheet_id": "0184d33a-c194-41af-9c16-486ed650494d",
  "xero_leave_ids": ["uuid1", "uuid2"],
  "entries_posted": 40,
  "work_hours": "36.00",
  "other_leave_hours": "0.00",
  "annual_sick_hours": "4.00",
  "unpaid_hours": "0.00",
  "errors": []
}

Or (error):
{
  "success": false,
  "xero_timesheet_id": null,
  "entries_posted": 0,
  "work_hours": "0.00",
  "other_leave_hours": "0.00",
  "annual_sick_hours": "0.00",
  "unpaid_hours": "0.00",
  "errors": ["Pay run for week 2025-11-10 to 2025-11-16 is already Posted and cannot be modified"]
}

Errors:
- 400: Validation errors (not Monday, missing staff_id)
- 403: Permission denied (can only post own timesheet, or manager for team)
- 404: Staff not found or no xero_user_id configured
- 500: Xero API errors
```

### 4. Get Week Summary

```
GET /api/payroll/week-summary/?week_start_date=2025-11-10

Response:
{
  "week_start_date": "2025-11-10",
  "week_end_date": "2025-11-16",
  "payment_date": "2025-11-19",
  "pay_run_status": "Draft",  // or "Posted" or null
  "staff": [
    {
      "staff_id": "uuid",
      "staff_name": "Tonya Harris",
      "work_hours": "36.00",
      "other_leave_hours": "0.00",
      "annual_sick_hours": "4.00",
      "unpaid_hours": "0.00",
      "total_entries": 40,
      "posted_to_xero": false,
      "last_posted_at": null
    },
    // ... more staff
  ]
}
```

## Backend Service Layer

**Already implemented:** `apps/timesheet/services/payroll_sync.py`

The REST API endpoints will call:

- `PayrollSyncService.post_week_to_xero(staff_id, week_start_date)` → Returns dict with results
- `create_pay_run(week_start_date)` from `apps/workflow/api/xero/payroll.py` → Returns id (Django PK) and xero_id

## Error Handling

### User-Friendly Error Messages

**Backend Error → Frontend Display:**

| Backend Error                                        | User Message                                                                                                                             |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| "week_start_date must be a Monday"                   | "Invalid date selected. Please select a Monday."                                                                                         |
| "No pay run found for week..."                       | "Please create a pay run for this week first using the 'Create Pay Run' button above."                                                   |
| "Pay run...is already Posted and cannot be modified" | "This week's payroll has already been finalized and paid. You cannot modify locked pay runs. Contact payroll if corrections are needed." |
| "Staff member...does not have a xero_user_id"        | "This staff member is not linked to Xero. Please contact your administrator to configure Xero integration for this user."                |
| "There can only be one draft pay run"                | "Another draft pay run exists for a different week. Please complete or delete it in Xero before creating a new one."                     |
| Connection/auth errors                               | "Unable to connect to Xero. Please try again or contact support if the problem persists."                                                |

## Permissions

- **Office Manager / Payroll Admin:** Can post any staff member's hours
- **Staff Member:** Can only post their own hours (if we allow self-posting, TBD)
- **Viewer:** Cannot post (read-only access to timesheets)

## Visual Design Notes

- Use existing Jobs Manager color scheme and component library
- Pay run status should be prominent and clear
- Posting progress/results should be non-intrusive but visible
- Error messages should be helpful and actionable
- Loading states should prevent double-posting

## Important Implementation Notes

1. **Week Selection:** The page should have a week picker. Default to current week, allow browsing past weeks.

2. **Locked Weeks:** Once a pay run is Posted in Xero, clearly indicate it's locked. Gray out post buttons, show lock icon.

3. **Re-posting:** If staff hours are edited after initial posting (but before pay run is Posted), allow re-posting. Backend will delete old lines and replace with new data.

4. **Zero Hours:** If staff has zero hours for the week, don't show them in the list (or show grayed out with "No hours entered").

5. **Validation:** Client-side validation for Monday dates before API calls.

6. **Confirmation:** Consider confirmation dialog for "Post to Xero" to prevent accidental posts.

## Testing Checklist for Frontend

- [ ] Create pay run button appears when no pay run exists
- [ ] Create pay run button hidden when pay run already exists
- [ ] Post buttons disabled when no pay run exists
- [ ] Post buttons disabled when pay run is Posted (locked)
- [ ] Loading states work correctly during posting
- [ ] Success message displays with correct breakdown
- [ ] Error messages are user-friendly
- [ ] Re-posting works after editing hours
- [ ] Page refreshes pay run status correctly
- [ ] Week picker changes week and updates all data
- [ ] Bulk post (if implemented) handles errors gracefully

## Next Steps

1. Backend Claude: Implement REST API endpoints (this document describes them)
2. Frontend Claude: Implement UI based on this spec
3. Test end-to-end with demo data
4. Deploy to staging for office manager testing
