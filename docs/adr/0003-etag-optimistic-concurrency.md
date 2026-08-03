# 0003 — ETag-based optimistic concurrency for Job and PO edits

Every Job and PO mutation requires an `If-Match` header with the latest ETag; missing → `428`, stale → `412`.

## Rules

- GETs return an `ETag` derived from `updated_at` (plus the primary key for delivery receipts) and honour `If-None-Match` with `304 Not Modified`.
- Mutating endpoints (`PUT`, `PATCH`, `DELETE`, and the domain-specific POSTs such as "Accept quote" or "Post delivery receipt") require `If-Match`. Missing header → `428 Precondition Required`; mismatched value → `412 Precondition Failed`. Clients recover from a `412` by refetching.
- The comparison happens inside the service layer under `select_for_update`, so check and write are atomic — a check-then-write race cannot slip through.
- CORS exposes `ETag` and allows `If-Match`/`If-None-Match`, so the cross-origin frontend can participate.

## Do not

- **A version integer in the request body** — the body carries data only (ADR 0006); preconditions belong in headers, where every HTTP layer already understands them.
- **Pessimistic locks for edit sessions** — users leave tabs open and locks time out badly; conflicts are rare enough that `412`-and-refetch is the cheaper failure.
