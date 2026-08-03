# 0030 — First-class People and Company links

`Person` owns human identity; `CompanyPersonLink` owns the relationship-at-company; jobs and calls point at the person.

## Rules

- `Person` owns identity (name, email) and person-owned contact methods. `CompanyPersonLink` owns relationship-at-company data (position, `is_primary`, notes, Xero import key). A person may link to multiple companies; deduplicating equivalent people is a separate data-quality task with its own service.
- Jobs, phone call records, Kanban, and search reference the person: `person_id` / `person_name`. Company contact APIs expose link rows with embedded person identity fields.
- A contact method is owned by exactly one `Company` or one `Person`. Phone sharing is allowed only when all owners trace to at least one common company; unedited legacy rows are grandfathered.
- DocketWorks owns Person identity. Xero contact-person payloads never create, reactivate, or update `Person` rows, and Person identity is never written back to Xero. `contact_id` / `xero_contact_id` keep their names — they are external Xero identifiers, not CRM people; legacy `contact_id` survives only where it refers to Xero.
- Company merge (ADR 0034) moves company-owned contact methods, company links, jobs, and call company ownership; it never moves person-owned contact methods.
