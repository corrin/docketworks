# 0030: First-class People and Company links

## Status

Accepted

## Context

The CRM originally treated a company contact as a row owned by one company. That
matched Xero's contact-person payload but made humans second-class: jobs, calls,
and phone numbers pointed at a company-specific contact shape instead of the
person. It also mixed two different concepts in one row: identity
(`name`, `email`) and relationship-at-company (`position`, `is_primary`, notes,
Xero import key).

## Decision

People are first-class records. `Person` owns human identity and person-owned
contact methods. `CompanyPersonLink` owns relationship-at-company data and the
stable `xero_name` key used to reconcile Xero contact persons for one company.

Jobs and phone call records point to `Person`. Company contact APIs expose link
rows with embedded person identity fields. Contact methods are owned by exactly
one `Company` or one `Person`. Phone sharing is allowed only when all owners
trace to at least one common company; unchanged legacy rows are grandfathered
until edited.

Xero company `contact_id` and `xero_contact_id` terminology remains unchanged
because those are external Xero identifiers, not CRM people.

## Consequences

- A person may have links to multiple companies; deduplicating equivalent people
  remains a separate data-quality task.
- Xero may create or reactivate links keyed by `(company, xero_name)`, but
  `Person.name` is user-owned after the initial seed.
- Company merge moves company-owned contact methods, company links, jobs, and
  call company ownership. It does not move person-owned contact methods.
- API callers use `person_id` and `person_name` for jobs, calls, Kanban, and
  search. Legacy `contact_id` survives only where it refers to Xero.
