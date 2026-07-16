# Test Plan: Company People Management

## Purpose

Verify that a Person has one identity, can be linked to one or more companies,
and can be managed from both the People directory and a company page.

## Preconditions

- Migrations are applied.
- The tester is signed in as office staff.
- At least two companies exist.

## People Directory

- [ ] Open `/crm/people` and confirm active people are listed once each.
- [ ] Search by person name, email, phone, and company name.
- [ ] Open a person and edit their name and email.
- [ ] Add, edit, make primary, and delete a contact method.
- [ ] Add a second company relationship and confirm the Person remains one record.
- [ ] Remove one relationship and confirm the Person and other relationship remain.

## Company People

- [ ] Open a company and confirm its active people are shown.
- [ ] Create a Person with name only and confirm the company link is created.
- [ ] Create a Person with email, phone, position, notes, and primary status.
- [ ] Link an existing Person from the People directory to the company.
- [ ] Confirm only one active Person link is primary for a company.
- [ ] Confirm creating a Person without an initial company is not offered.

## Duplicate-Phone Decisions

- [ ] Enter an unused phone and confirm a new Person can be created.
- [ ] Enter a phone used by another Person at the same company and confirm the UI
      allows creation because an office number may be shared.
- [ ] Enter a phone owned by a Person at another company and confirm the UI offers
      the existing Person for linking instead of creating a duplicate.
- [ ] Link that existing Person and confirm both company relationships are visible.
- [ ] Attempt to remove a relationship when that would turn a shared phone into an
      unexplained cross-company collision; confirm removal is blocked with a clear
      validation message.

## Job Integration

- [ ] On a job with a company, select one of that company's people.
- [ ] Create a Person from the job Person control and confirm it receives the job's
      company as its initial relationship.
- [ ] Reload and confirm the selected Person persists.
- [ ] On a job without a company, confirm a Person cannot be created until a company
      is selected.

## API Checks

- [ ] `GET /api/people/?q=<term>` returns each matching Person once.
- [ ] `GET /api/people/<person_id>/` separates identity from company links.
- [ ] `GET /api/companies/<company_id>/people/` returns active company people.
- [ ] `POST /api/companies/<company_id>/people/` creates the Person and initial link
      atomically, or returns the structured phone conflict without partial writes.
- [ ] `PUT` and `DELETE /api/people/<person_id>/company-links/<company_id>/` update only
      the relationship.
- [ ] The removed `/api/companies/person-links/` collection returns 404.

## Sign-off

- [ ] Focused backend and frontend tests pass.
- [ ] End-to-end tests pass and global teardown restores the database.
- [ ] Migration and workflows are rehearsed against a disposable production copy.
- [ ] Production-copy counts and ownership integrity checks pass before and after.
- [ ] User acceptance testing is complete.
