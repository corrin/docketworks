# 0004 — Job mutations require a self-contained delta envelope

Clients submit `{change_id, fields, before, after, before_checksum, etag}` for every Job update; the backend re-canonicalises, verifies the checksum, persists a structured `JobEvent` for undo, and logs rejections to `JobDeltaRejection`.

## Problem

ETag concurrency (ADR 0003) protects against concurrent writes but doesn't prove the client based its change on the state it *thought* it did — an intervening mutation that happens to leave `updated_at` unchanged slips through. Separately, undo against a full-PUT model means "restore every field" — the server can't tell which field the user actually meant to change.

## Decision

Every `PUT`/`PATCH` to a Job carries an envelope: `{change_id, actor_id, made_at, job_id, fields, before, after, before_checksum, etag}`. The backend recomputes `before_checksum` over a canonical serialisation of the named fields and rejects the request if it doesn't match the current DB state. Canonicalisation is `compute_job_delta_checksum` (sorted keys, `__NULL__` sentinel for `None`, trimmed strings, normalised decimals, ISO-8601-UTC dates with millisecond precision) mirrored bit-identical in Python and TypeScript. Accepted deltas write a `JobEvent` with `delta_before`, `delta_after`, `delta_meta`, `delta_checksum`. Rejected envelopes go to `JobDeltaRejection`. `If-Match` is still required.

## Why

The envelope captures *intent*: what the user thought they were changing, not just the resulting state. That makes undo a backend operation (`POST /jobs/{id}/undo-change/` generates the reversing envelope server-side) instead of a client guess. The checksum catches the case where two serialisations share an `updated_at`. Rejected payloads in `JobDeltaRejection` give support a real artefact when a user reports "my edit didn't save."

## Alternatives considered

- **Full-resource PUT (replace entire job).** REST norm. Rejected: undo loses intent; one-field edits conflict with unrelated field changes.
- **Checksum over the entire job state.** Avoids naming changed fields. Rejected: same conflict problem; intent is still lost.
- **No checksum, ETag alone.** What we had. Rejected: `updated_at` collisions are rare but real, and there's no per-field audit trail.

## Consequences

Intent is preserved; undo is backend-generated; rejected payloads are inspectable. Cost: two canonicalisation implementations (Python + TypeScript) must stay bit-identical — any drift is a silent rejection.
