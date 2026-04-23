# 0004 — Job mutations require a self-contained delta envelope

Clients submit a `{change_id, fields, before, after, before_checksum, etag}` envelope for every Job update; the backend re-canonicalises, verifies the checksum, persists a structured `JobEvent` for undo, and logs rejections to `JobDeltaRejection`.

- **Status:** Accepted
- **Date:** 2025-10-08
- **PR(s):** Commits `1a8fb893` (validation + OCC, 2025-10-08), `824760c4` (envelope + `JobDeltaRejection`, 2025-10-09), `86b80639` (undo, 2025-10-09) — predates GitHub PR workflow

## Context

ETag-level concurrency (ADR 0003) protects against concurrent writes but doesn't prove the client based its change on the state it *thinks* it did — an intervening mutation that happened to leave `updated_at` unchanged would slip through. We also wanted structured audit events (`JobEvent` with before/after) for undo, and we wanted to reject legacy raw-payload mutations so every integration routes through a documented envelope.

## Decision

Every `PUT`/`PATCH` to a Job must submit a delta envelope: `{change_id, actor_id, made_at, job_id, fields, before, after, before_checksum, etag}`. The backend recomputes `before_checksum` over the canonical serialisation of the named fields and rejects the request if it doesn't match the current DB state. Canonicalisation is the shared `compute_job_delta_checksum` function (sorted field keys, `__NULL__` sentinel for `None`, trimmed strings, decimals normalised, dates ISO-8601-UTC with millisecond precision) mirrored in both Python and TypeScript. Rejected envelopes are persisted to `JobDeltaRejection` for diagnostics. Accepted deltas write a `JobEvent` with `delta_before`, `delta_after`, `delta_meta`, `delta_checksum` — enough to support `POST /jobs/{id}/undo-change/` which generates the reversing envelope server-side. `If-Match` from ADR 0003 is still required.

## Alternatives considered

- **Full-resource PUT (replace entire job):** expensive on the wire and makes undo mean "restore every field," losing the intent of what the user actually changed.
- **Checksum over the entire job state:** avoids having to name the fields changed, but defeats intent preservation and means a one-field edit conflicts with any other unrelated field change.
- **No checksum, rely on ETag alone:** the original approach; cannot detect the case where two serialisations happen to share an `updated_at`.

## Consequences

- **Positive:** intent is preserved (we know *which* fields changed), undo is a backend-generated reversing envelope rather than a client guess, rejected payloads are inspectable in `JobDeltaRejection` when support needs to debug a failed edit.
- **Negative / costs:** two canonicalisation implementations (Python and TypeScript) that must stay bit-identical — any drift is a silent rejection. Frontend has to maintain a per-job delta queue and process it sequentially. Legacy callers get `400` and must upgrade.
- **Follow-ups:** any future integration (CLI, scheduler) that writes jobs must either build the envelope or route through backend services that build it.
