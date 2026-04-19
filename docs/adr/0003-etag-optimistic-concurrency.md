# 0003 — ETag-based optimistic concurrency for Job and PO edits

Every Job and PO mutation requires an `If-Match` header carrying the latest ETag; the server rejects mismatches with `412` and missing headers with `428`, atomically under `select_for_update`.

- **Status:** Accepted
- **Date:** 2025-10-06
- **PR(s):** Commits `19c1748e` (Job ETags, 2025-10-06), `4e080aff` (Purchase Order ETags, 2025-10-30), `cbbd6ad5` (Delivery Receipts, 2025-10-31) — predates GitHub PR workflow

## Context

Two users editing the same Job (or Purchase Order) concurrently could silently overwrite each other's changes. Rapid double-submission of the same action — "Add event," "Accept quote," "Post delivery receipt" — produced duplicate side effects. There was no way for the backend to tell whether a mutation was targeting the version of the resource the client actually saw.

## Decision

GET endpoints return an `ETag` header derived from `updated_at` (plus the primary key for delivery-receipt endpoints). Mutating endpoints (`PUT`, `PATCH`, `DELETE`, and the domain-specific POSTs — add event, accept quote, process delivery receipt) require `If-Match` with the latest ETag. Missing header → `428 Precondition Required`. Mismatch → `412 Precondition Failed`. The check happens inside the service layer under `select_for_update`, so the comparison and the write are atomic. GETs accept `If-None-Match` for `304 Not Modified`. CORS is configured to expose `ETag` and allow `If-Match` / `If-None-Match` so a cross-origin frontend can participate.

## Alternatives considered

- **Pessimistic row locking across the whole edit session:** requires a lock-release protocol and times out poorly on tabs left open; the UX cost (lockouts) outweighs the very low conflict rate we actually see.
- **Version integer in the request body:** equivalent semantics but muddles the contract (body = data; identifiers and preconditions should be in headers/URL per ADR 0006).
- **Client-side "last write wins":** what we had; the reason for this change.

## Consequences

- **Positive:** concurrent edits surface as a well-defined `412` the client can recover from by refetching; double-submission no longer produces duplicate events; `304` on conditional GETs saves bandwidth for unchanged resources.
- **Negative / costs:** every client that mutates a Job/PO now has to track ETags per resource id; forgetting to include `If-Match` is a `428` rather than a silent overwrite (good, but it's a migration cost for callers); CORS configuration has to keep `ETag` in the expose-headers list forever.
- **Follow-ups:** extended the same pattern to delivery receipts; the job-delta delivery envelope (ADR 0004) layers on top and still requires `If-Match`.
