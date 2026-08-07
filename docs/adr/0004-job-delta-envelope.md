# 0004 — Job mutations require a self-contained delta envelope

Every Job update carries `{change_id, actor_id, made_at, job_id, fields, before, after, before_checksum, etag}`; the backend verifies the checksum against current state and records the delta.

## Rules

- Every `PUT`/`PATCH` to a Job carries the envelope `{change_id, actor_id, made_at, job_id, fields, before, after, before_checksum, etag}`. `If-Match` (ADR 0003) is still required; the checksum additionally catches intervening mutations that leave `updated_at` unchanged, and the named `fields` capture which values the user actually meant to change.
- The backend recomputes `before_checksum` with `compute_job_delta_checksum` over a canonical serialisation of the named fields — sorted keys, `__NULL__` sentinel for `None`, trimmed strings, normalised decimals, `date` as `YYYY-MM-DD`, `datetime` as ISO-8601 UTC at exactly millisecond precision — and rejects the request on mismatch. Golden vectors cover both temporal kinds (`scripts/generate/gen_delta_goldens.py`).
- The canonicalisation exists twice, Python and TypeScript, and must stay bit-identical; golden vectors guard it. Any drift silently rejects every affected edit. This is a deliberate protocol-parity exception to ADR 0020's "the frontend never recomputes" rule: the checksum is protocol plumbing, not a business value.
- Accepted deltas write a `JobEvent` (`delta_before`, `delta_after`, `delta_meta`, `delta_checksum`). Rejected envelopes are stored in `JobDeltaRejection` — the artefact support reaches for when a user reports "my edit didn't save".
- Undo is server-side: `POST /jobs/{id}/undo-change/` generates the reversing envelope from the recorded delta. Clients never reconstruct prior state.
