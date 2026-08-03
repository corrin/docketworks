# 0034 — Company identity and merges are Xero-first

Duplicate companies are merged in Xero; DocketWorks mirrors the merge and keeps the loser as a permanent tombstone.

## Rules

- A duplicate pair is merged **in Xero**; DocketWorks never pushes a merge (Xero's API cannot merge contacts, and Xero owns the invoices and receivables the merge must not split). On the next sync or webhook, the losing contact's `MergedToContactID` drives `company_merge_service.merge_companies()`: set `merged_into` on the local loser and reassign everything it owned — jobs, invoices, bills, credit notes, quotes, purchase orders, person links, call records, company-owned contact methods — to the winner.
- The loser is never deleted. Tombstone semantics: `merged_into` set, `allow_jobs` false, excluded from lists and pickers, still resolvable by id — future webhooks and documents still carry its `xero_contact_id`, and deleting the row would recreate the duplicate from scratch. `Company.get_final_company()` follows the chain so late-arriving documents land on the winner.
- Every path that retires a duplicate — including operator tooling for local-only companies — goes through the same service. The rule is total because every company is Xero-linked by construction: CRM creation pushes to Xero immediately and abandons the local row if the push fails. Detection (the duplicate-identities report) may recommend a canonical company but never performs remediation itself.
- `allow_jobs` follows Xero archive **transitions** only: archiving a contact disables jobs, un-archiving restores them, and a steady-state sync never touches the flag — so an operator's manual block on an active company survives routine syncs. Exception: un-archiving a merged tombstone never re-enables jobs, because its jobs belong to the winner. To durably block a company, archive it in Xero.
- Sync paths skip merged companies rather than re-importing data (phone numbers, addresses) the winner now owns.
- Person records are linked to the winner, not merged: `CompanyPersonLink` rows move, deduplicated against the winner's existing links (ADR 0030). Tombstones must be filtered wherever companies are listed or picked.

## Do not

- **The legacy `merge_companies` management command** (exact-name matching, pre-dating this decision) — it has no remaining remit; deleting it after a feature-parity inventory is tracked on KAN-325.
