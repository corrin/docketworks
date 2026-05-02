# 0003 — ETag-based optimistic concurrency for Job and PO edits

Every Job and PO mutation requires an `If-Match` header carrying the latest ETag; the server rejects mismatches with `412` and missing headers with `428`, atomically under `select_for_update`.

## Problem

Two users editing the same Job or PO concurrently silently overwrote each other. Rapid double-submission of the same action ("Add event," "Accept quote," "Post delivery receipt") produced duplicate side effects. The server had no way to tell whether a mutation was targeting the version the client actually saw.

## Decision

GETs return an `ETag` derived from `updated_at` (plus the primary key for delivery receipts). Mutating endpoints (`PUT`, `PATCH`, `DELETE`, and the domain-specific POSTs) require `If-Match` with the latest ETag. Missing → `428 Precondition Required`. Mismatch → `412 Precondition Failed`. The check happens inside the service layer under `select_for_update`, so comparison and write are atomic. GETs accept `If-None-Match` for `304 Not Modified`. CORS exposes `ETag` and allows `If-Match` / `If-None-Match` so a cross-origin frontend can participate.

## Why

ETags are the HTTP-native concurrency primitive: every layer (browser cache, reverse proxy, generated client) already understands them. Putting the precondition in the header keeps the request body free of plumbing fields. Doing the comparison under `select_for_update` makes it impossible for a check-then-write race to slip through.

## Alternatives considered

- **Pessimistic row locking for the edit session.** Legitimate in low-concurrency, high-cost-of-conflict domains (banking, inventory). Rejected: humans leave tabs open, locks time out poorly, conflict rate is low.
- **Version integer in the request body.** Many serious REST APIs do this. Rejected: muddles the body contract — body should be data; preconditions belong in headers. See ADR 0006.

## Consequences

Concurrent edits surface as a well-defined `412` the client can recover from by refetching; double-submission stops producing duplicate events; `304` on conditional GETs saves bandwidth. Every client that mutates a Job/PO must track ETags per resource id; forgetting `If-Match` is a `428` rather than a silent overwrite (good, but a migration cost).
