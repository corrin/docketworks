● Job Aging Report Frontend Requirements

API Endpoint

- URL: /accounting/api/reports/job-aging/
- Method: GET
- Query Parameters:
  - include_archived (optional): boolean, default false - includes archived jobs when true

API Response Format

{
"jobs": [
{
"id": "uuid-string",
"job_number": 1234,
"name": "Job Name",
"client_name": "Client Name",
"status": "in_progress",
"status_display": "In Progress",
"financial_data": {
"estimate_total": 5000.00,
"quote_total": 4800.00,
"actual_total": 4750.00
},
"timing_data": {
"created_date": "2024-01-15",
"created_days_ago": 45,
"days_in_current_status": 12,
"last_activity_date": "2024-02-27",
"last_activity_days_ago": 1,
"last_activity_type": "time_entry",
"last_activity_description": "Time added by John Smith"
}
}
]
}

Frontend Requirements

1. Data Table Display

- Primary view: Sortable data table with the following columns:
  - Job Number (sortable, clickable link to job details)
  - Job Name (sortable)
  - Client Name (sortable)
  - Status (sortable, with color coding)
  - Days in Status (sortable, highlight >30 days)
  - Job Age (days since created, sortable)
  - Last Activity (sortable, highlight >14 days)
  - Financial Summary (estimate/quote/actual totals)

2. Filtering & Controls

- Include Archived Jobs: Toggle checkbox to include archived jobs
- Status Filter: Multi-select dropdown for job statuses
- Age Range Filter: Slider or input for job age (days)
- Last Activity Filter: Dropdown for activity age thresholds (7, 14, 30, 60+ days)

3. Visual Indicators

- Status Colors: Use consistent color scheme matching existing job status colors
- Age Warnings:
  - Red: >60 days with no activity
  - Yellow: >30 days with no activity
  - Green: Recent activity (<7 days)
- Financial Progress: Visual indicator comparing estimate → quote → actual

4. Sorting & Pagination

- Default Sort: Last activity (oldest first) to surface stale jobs
- Secondary Sort: Job age for tie-breaking
- Pagination: Handle large datasets (100+ jobs)

5. Export Functionality

- CSV Export: All visible data with current filters applied
- Print View: Clean table format suitable for printing

6. Performance Considerations

- Loading States: Show loading spinner while fetching data
- Error Handling: Display user-friendly error messages for API failures
- Caching: Consider caching data for 5-10 minutes to reduce API calls
- Auto-refresh: Optional periodic refresh every 15-30 minutes

7. Navigation Integration

- Job Links: Job numbers should link to existing job detail pages
- Client Links: Client names should link to client detail pages
- Breadcrumbs: Include in existing accounting reports navigation

8. Responsive Design

- Mobile View: Collapse to essential columns (Job #, Name, Status, Age)
- Tablet View: Show most columns with horizontal scrolling if needed
- Desktop View: Full table with all columns visible

9. Integration Points

- Menu Location: Add to Accounting → Reports section
- Permissions: Respect existing user permissions for job/client access
- Styling: Use existing Bootstrap/CSS framework and color schemes

10. Optional Enhancements

- Drill-down: Click on last activity to see detailed activity history
- Bulk Actions: Select multiple jobs for status updates
- Dashboard Widget: Summary stats (total jobs, avg age, stale jobs count)
- Charts: Visual representation of job age distribution

Technical Notes

- API returns financial amounts as numbers (not strings)
- Date fields are ISO format strings
- All IDs are UUID strings
- Empty/null values are handled gracefully in the response
- API is read-only (no POST/PUT/DELETE operations)

This frontend implementation will provide a comprehensive job aging report that helps identify stale jobs and track project progress across the business.
