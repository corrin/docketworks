# 0030 — Person owns identity, CompanyPersonLink owns the relationship, jobs point at the person

`Person` owns human identity; `CompanyPersonLink` owns the relationship-at-company; jobs and calls point at the person.

## Rules

- `Person` owns identity (name, email) and person-owned contact methods. `CompanyPersonLink` owns relationship-at-company data (position, `is_primary`, notes, Xero import key). A person may link to multiple companies; deduplicating equivalent people is a separate data-quality task with its own service.
- Jobs, phone call records, Kanban, and search reference the person: `person_id` / `person_name`. Company contact APIs expose link rows with embedded person identity fields.
- A contact method is owned by exactly one `Company` or one `Person`. One number belongs to one person, and that person may be linked to several companies, so a number that appears on two companies through the same person is legitimate (owner ruling 2026-09-12: the owner-operator who is both a customer and a supplier). Nothing is grandfathered: a number held by two different people is a data defect to merge, never a legacy row to tolerate (ADR 0059).
- DocketWorks owns Person identity. Xero contact-person payloads never create, reactivate, or update `Person` rows, and Person identity is never written back to Xero. `contact_id` / `xero_contact_id` keep their names — they are external Xero identifiers, not CRM people; legacy `contact_id` survives only where it refers to Xero.
- Company merge (ADR 0034) moves company-owned contact methods, company links, jobs, and call company ownership; it never moves person-owned contact methods.
