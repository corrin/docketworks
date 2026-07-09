# Test Plan: Company People Management Feature

## Overview

This test plan covers company people management: people are stored locally,
linked to companies, and selected on jobs without relying on Xero contact-person
sync for day-to-day job assignment.

## Prerequisites

- [ ] Ensure migrations have been applied (`python manage.py migrate`)
- [ ] Have at least one company in the system
- [ ] Have access to create and edit jobs

## Test Cases

### 1. View Existing Person Data

- [ ] Navigate to an existing job that has person and phone data
- [ ] Verify the person information is displayed in the read-only field
- [ ] Verify format is "Name - Phone" or just "Name" if no phone

### 2. Open Person Management Modal

- [ ] Click the "Manage" button next to the Person field
- [ ] Verify modal opens with:
  - [ ] Company name displayed at top
  - [ ] List of existing people (if any)
  - [ ] Form to add a new person

### 3. Create New Person

- [ ] In the modal, fill in the new person form:
  - Name: "John Smith" (required)
  - Position: "Project Manager" (optional)
  - Email: "john@example.com" (optional)
  - Phone: "555-1234" (optional)
  - Notes: "Primary contact for all orders" (optional)
  - Check "Set as primary contact"
- [ ] Click "Save Person"
- [ ] Verify modal closes
- [ ] Verify person display updates to "John Smith - 555-1234"
- [ ] Verify hidden person_id field is populated
- [ ] Verify autosave triggers (check network tab or console)

### 4. Select Existing Person

- [ ] Open modal again
- [ ] Verify "John Smith" appears in the existing people list with "Primary" badge
- [ ] Add another person "Jane Doe" without marking as primary
- [ ] Close and reopen modal
- [ ] Click "Select" button next to "Jane Doe"
- [ ] Click "Save Person"
- [ ] Verify person display updates to "Jane Doe"

### 5. Person Without Company

- [ ] Create a new job or use one without a company selected
- [ ] Click "Manage" person button
- [ ] Verify modal shows warning: "Please select a company first."
- [ ] Verify Save button is disabled

### 6. Primary Person Behavior

- [ ] For a company with multiple people, mark a different one as primary
- [ ] Verify only one person can be primary at a time
- [ ] Verify primary people appear first in the list

### 7. Autosave Integration

- [ ] Select/create a person for a job
- [ ] Make another change to the job (e.g., change job name)
- [ ] Verify both changes are saved
- [ ] Refresh the page
- [ ] Verify person selection persists

### 8. API Testing (Developer Console)

- [ ] Test fetching company people:

```javascript
// Replace [COMPANY_ID] with actual company UUID
fetch("/api/companies/person-links/?company_id=[COMPANY_ID]")
  .then((r) => r.json())
  .then(console.log);
```

- [ ] Test creating a person link:

```javascript
// Replace [COMPANY_ID] with actual company UUID
fetch("/api/companies/person-links/", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value,
  },
  body: JSON.stringify({
    company: "[COMPANY_ID]",
    person_name: "Test Person",
    person_email: "test@example.com",
    phone: "555-5555",
    is_primary: false,
  }),
})
  .then((r) => r.json())
  .then(console.log);
```

### 9. Edge Cases

- [ ] Try to save without selecting any person (should close modal without changes)
- [ ] Create a person with only name (minimum required field)
- [ ] Create a person with very long name/phone/email
- [ ] Try special characters in person fields

### 10. Migrated Data

- [ ] Find a job with migrated person/phone data
- [ ] Verify it displays correctly
- [ ] Select a new person from modal
- [ ] Verify the job stores the selected person_id

### 11. Multiple Browser Testing

- [ ] Test in Chrome
- [ ] Test in Firefox
- [ ] Test in Safari (if available)
- [ ] Test in Edge

### 12. Performance Testing

- [ ] Test with a company that has 50+ people
- [ ] Verify modal loads quickly
- [ ] Verify people list is scrollable and responsive

## Expected Results

- All person data is stored locally in Person and CompanyPersonLink models
- No API calls to Xero for person management
- Smooth user experience with modal interface
- Primary person designation works correctly

## Known Limitations

- Person email is not currently displayed in the selection (only name and phone)
- No search/filter functionality in the people list yet
- No bulk import of people

## Rollback Plan

If critical issues are found:

1. Reverse to the previous migration checkpoint in a development copy.
2. Restore the previous branch if production rollout is blocked.
3. Hide the modal by removing the "Manage" button from the template if needed.

## Sign-off

- [ ] Developer testing complete
- [ ] User acceptance testing complete
- [ ] Ready for production deployment

---

_Test Plan Created: 2025-06-09_
_Feature: Company People Management_
_Version: 1.0_
