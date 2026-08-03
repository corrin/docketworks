# 0034 — Company identity and merges are Xero-first

Duplicate companies are merged in Xero; DocketWorks mirrors the merge and keeps the loser as a permanent tombstone.

## Problem

The same real-world business ends up as two Company rows — imported twice into Xero, typed twice at the counter, or created under a trading name. Each duplicate splits the customer's jobs, invoices, people, and phone numbers across two records, and every consumer that assumes one-company-one-identity (phone-number ownership, receivables, CRM history) degrades. Merging is therefore routine data hygiene, but a merge touches two systems: DocketWorks and Xero both hold the contact, and only one of them can be the source of truth for which record survives.

## Decision

Xero is authoritative for company identity. A duplicate pair that exists in Xero is merged **in Xero**; DocketWorks never pushes a merge to Xero. On the next sync or webhook, DocketWorks reads the losing contact's `MergedToContactID`, sets `merged_into` on the local loser, and reassigns everything the loser owned — jobs, invoices, bills, credit notes, quotes, purchase orders, person links, call records, and company-owned contact methods — to the winner via `company_merge_service.merge_companies()`.

The loser is never deleted. It remains as a tombstone: `merged_into` set, `allow_jobs` false, excluded from lists and pickers, still resolvable by id. `Company.get_final_company()` follows the chain, so a Xero document arriving against a retired contact always lands on the surviving company. Tombstone semantics are the only semantics — every code path that retires a duplicate, including operator tooling for companies that exist only locally, goes through the same service.

Person records are linked to the winner, not merged: company merge moves `CompanyPersonLink` rows (deduplicating against the winner's existing links) and leaves person-owned contact methods with the person, per ADR 0030. Deduplicating the people themselves is a separate task with its own service.

`allow_jobs` follows the Xero archive state on its transitions: archiving a contact disables jobs, un-archiving restores them. Only the transitions act — a steady-state sync never touches the flag, so an operator's manual block on an active company survives routine syncs. A merged tombstone is the exception: un-archiving its contact never re-enables jobs, because its jobs belong to the winner. The corollary is that Xero is also where blocking belongs — to durably stop a company taking jobs, archive it in Xero rather than relying on the local toggle.

## Why

A merge must happen where the money lives. Xero owns invoices, payments, and the contact ledger; a merge done only in DocketWorks leaves the duplicate active in Xero, still accepting invoices and splitting the customer's receivables — locally tidy, financially wrong. Xero also already broadcasts merges (`MergedToContactID` survives on the archived contact), which gives DocketWorks a durable signal to converge on without any coordination protocol of its own.

Tombstones rather than deletion because the retired row is load-bearing: it holds the `xero_contact_id` that future webhooks and documents will still reference, and deleting it would turn every late-arriving reference into a dangling id.

## Alternatives considered

- **Merge in DocketWorks and push to Xero:** Xero's API does not expose contact merging, so this is not implementable — only archiving, which silently strands the duplicate's Xero-side history.
- **Bidirectional merge with conflict resolution:** two writable sources of identity truth need a reconciliation protocol and still disagree during the window. One authority is simpler and sufficient.
- **Hard-delete the loser after reassignment:** leaves nothing for `get_final_company()` to resolve; any Xero document or webhook that still names the old contact id would create the duplicate again from scratch.

## Consequences

Operators need exactly one rule: merge it in Xero and let DocketWorks follow. This rule is total because every company is Xero-linked by construction — creating a company in the CRM pushes it to Xero immediately and abandons the local row if the push fails — so every duplicate pair is a Xero-linked pair. Detection (the duplicate-identities report) can recommend a canonical company without owning remediation. The costs: tombstones accumulate forever and must be filtered wherever companies are listed or picked, and a merged company's archived Xero contact keeps its phone numbers, so sync paths must skip merged companies rather than re-import data the winner now owns. The legacy `merge_companies` management command (exact-name matching, from the KAN-278 cleanup) predates this decision and has no remaining remit; replacing it with report-driven tooling and deleting it — after a feature-parity inventory — is tracked on KAN-325.
