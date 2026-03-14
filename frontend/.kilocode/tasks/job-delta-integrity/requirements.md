# Job Delta Integrity - Frontend Requirements

Source: docs/jobview-delta-control-guide.md

Goal: All Job mutations (PUT/PATCH `/job/rest/jobs/:job_id/`) must submit a self-contained delta envelope alongside existing ETag (`If-Match`) control. The frontend must construct, queue, and submit envelopes; compute `before_checksum` deterministically; and integrate cleanly with current ETag reload-and-retry UX.

Envelope (v1):

- `change_id`: uuid-v4, stable across retries
- `actor_id`: staff uuid (from auth store)
- `made_at`: ISO8601 UTC with ms, `Z` suffix
- `job_id`: job uuid
- `fields`: changed keys (sorted in checksum; ordering free-form in metadata)
- `before`: map of original values for changed fields (pre-change snapshot)
- `after`: map of new values for changed fields
- `before_checksum`: sha256 of canonical string: `{job_id}|{field}={value}|...`
- `etag`: current ETag associated with the job (also sent via `If-Match` header by axios interceptor)

Canonicalisation rules (must mirror backend):

- Sort field keys alphabetically for checksum input
- Null/undefined -> literal `"__NULL__"`
- Trim strings for comparison; use the trimmed value in checksum
- Decimals as plain strings without exponent or trailing zeros (e.g. `5.10` -> `"5.1"`)
- Date -> `YYYY-MM-DD`
- Datetime -> ISO 8601 UTC with ms precision, `Z` suffix
- Booleans -> `"true"` or `"false"`
- Lists -> `[item1,item2,...]` with each item canonicalised

Interaction & queueing (frontend responsibilities):

- Maintain per-job buffering/queue; build deltas only against the latest local snapshot
- Submit sequentially; update snapshot and propagate new ETag on success
- On 412/428: pause queue, reload job + header + basic info to refresh ETag/state, surface persistent Retry UX
- On 400/409: show validation/structural errors inline; allow delta amend + retry

Undo support (phase 2):

- Fetch Job events enriched with `schema_version`, `change_id`, `delta_*` metadata
- POST `/job/rest/jobs/:job_id/undo-change/` with `change_id` + `If-Match`

Non-goals for this phase:

- Rewriting global autosave architecture; we will adapt the existing autosave pipeline
- Implementing a timeline UI; only plumbing necessary props for future UI

Success criteria:

- Header autosave emits compliant envelopes; backend accepts and records structured events
- ETag conflicts reload cleanly; Retry replays user changes by rebuilding envelope on top of fresh data
- Deterministic checksum parity proven by unit tests for representative cases

Schema status:

- The generated API already includes `schemas.JobDeltaEnvelope`, `schemas.PatchedJobDeltaEnvelope`, `schemas.JobUndoRequest`, and endpoints `job_rest_jobs_update`, `job_rest_jobs_partial_update`, and `job_rest_jobs_undo_change_create`. We will rely on these directly.
