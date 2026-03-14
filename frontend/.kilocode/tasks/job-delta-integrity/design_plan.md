# Job Delta Integrity - Design Plan

Overview: Integrate delta envelope submission into the existing autosave and ETag system with minimal disruption. Build a deterministic checksum utility, a delta builder, and a submission path that reuses our generated Zodios client and interceptors (which already manage `If-Match` and conflict toasts/reloads).

Key integration points

- ETags: Keep using api/client.ts interceptors. Also embed the same ETag string in `envelope.etag`.
- Autosave: Extend current `createJobAutosave` consumers (starting with `useJobHeaderAutosave.ts`) to produce envelopes per flush and submit via a new `submitDelta` service.
- Store snapshots: Use `jobsStore.getHeaderById(jobId)` as the canonical “before” source for header fields, and the autosave patch as “after”.

New utilities (src/utils)

- `deltaChecksum.ts` (pure):
  - `canonicaliseValue(value): string` - implements null sentinel, trim, boolean, date/datetime, decimal normalisation, lists
  - `serialiseForChecksum(jobId: string, before: Record<string, unknown>, fields?: string[]): string` - sort keys, build `{job_id}|field=value|...`
  - `sha256Hex(input: string): Promise<string>` - Web Crypto Subtle Crypto with text encoder, hex output (throws if `crypto.subtle` unavailable)
  - `computeJobDeltaChecksum(jobId: string, before: Record<string, unknown>, fields: string[]): Promise<string>`

Types

- Use generated types: `z.infer<typeof schemas.JobDeltaEnvelope>` and `z.infer<typeof schemas.PatchedJobDeltaEnvelope>`.

- Delta builder (src/composables/useJobDelta.ts)
- `buildJobDeltaEnvelope(partial: Partial<JobDeltaEnvelope> & { before: Record<string, unknown>; after: Record<string, unknown>; fields: string[] }): Promise<JobDeltaEnvelope>` - computes checksum and returns envelope, parsing with generated schema
- `useJobDeltaQueue(jobId: string)` - thin wrapper over our autosave cycle to:
  - maintain lastChangeId across retries
  - capture last submitted envelope for logging/debug

Service (src/services/delta.service.ts)

- `submitJobDelta(jobId: string, envelope: z.infer<typeof schemas.JobDeltaEnvelope>)` - use generated client:
  - `api.job_rest_jobs_partial_update(envelope, { params: { job_id } })`
  - Relies on interceptors to attach `If-Match` and capture new `ETag`.
  - On success: return updated `JobDetailResponse`; on 400/409: surface errors; on 412/428: interceptors trigger pause/reload and user Retry.

Header autosave integration

- In `useJobHeaderAutosave.ts`:
  - Keep the allowlist of header fields
  - On flush: compute `before` from `originalHeader` (store), `after` from `filteredPatch`
  - Derive `fields` from patch keys sorted
  - Get `actor_id` from `authStore.user?.id`; fall back to empty string if missing (and reject early)
  - Get `etag` from `useJobETags().getETag(jobId)`
  - Generate or reuse a `change_id` (persist across retries using autosave’s `lastConflictPatch` token)
  - Build and submit envelope via `submitJobDelta`
  - Preserve current conflict handling (pausedDueToConflict + Retry button wiring)

Schema/client alignment

- Updated schemas already include:
  - Types: `schemas.JobDeltaEnvelope`, `schemas.PatchedJobDeltaEnvelope`, `schemas.JobUndoRequest`.
  - Endpoints: `api.job_rest_jobs_update` (PUT), `api.job_rest_jobs_partial_update` (PATCH), and `api.job_rest_jobs_undo_change_create` (POST).
  - We will use these directly; no axios bridge required.

Testing

- Unit tests for `deltaChecksum.ts` covering:
  - strings with whitespace, null/undefined, booleans, date/datetime (UTC `Z`), numbers/decimals (trailing zero trim), lists
  - stable ordering of fields and full hex digest for known fixtures
- Integration test for `buildJobDeltaEnvelope` given a mock header snapshot and patch
- Manual QA checklist (multi-tab/concurrency, retry, rapid edits coalescing, offline/online)

Rollout

- Phase 1: Header autosave only
- Phase 2: Other Job tabs/forms (description, notes, delivery_date, etc.) using the same builder/service
