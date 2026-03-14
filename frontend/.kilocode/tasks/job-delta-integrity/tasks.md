# Job Delta Integrity - Tasks

This checklist focuses on Job header autosave first, integrating with the existing ETag flow. Follow the order for minimal disruption.

1. Utilities and Types

- [x] Add `src/utils/deltaChecksum.ts` implementing canonicalisation + `computeJobDeltaChecksum`
- [x] Use generated types from `schemas` (`JobDeltaEnvelope`, `PatchedJobDeltaEnvelope`, `JobUndoRequest`); no custom envelope type

2. Delta Builder + Queue Glue

- [x] Add `src/composables/useJobDelta.ts` with:
  - [x] `buildJobDeltaEnvelope(partial: Partial<JobDeltaEnvelope>)` that requires `before`, `after`, `fields`, computes checksum, and returns a parsed `schemas.JobDeltaEnvelope`
  - [x] `useJobDeltaQueue(jobId)` thin wrapper to persist `lastChangeId` across retries

3. Submission Service

- [x] Add `src/services/delta.service.ts` with `submitJobDelta(jobId, envelope)`
  - [x] Use generated client: `api.job_rest_jobs_partial_update(envelope, { params: { job_id } })`

4. Wire Into Header Autosave

- [x] Update `src/composables/useJobHeaderAutosave.ts` `saveAdapter` to:
  - [x] Build `filteredPatch` as today (allowlist)
  - [x] Compute `before` from `originalHeader` store snapshot (only changed keys)
  - [x] Compute `fields` (sorted keys of patch)
  - [x] Resolve `actor_id` from `authStore.user?.id`, guard + error if missing
  - [x] Resolve `etag` via `useJobETags().getETag(jobId)`
  - [x] Build envelope and call `submitJobDelta`
  - [x] Maintain existing conflict pause and true Retry behaviour (rebuild envelope on retry with fresh `before`)

5. Tests + QA

- [x] Add `src/utils/__tests__/deltaChecksum.test.ts` covering canonical rules and a fixed checksum fixture
- [x] Add `docs` note: quick manual validation checklist for header edits, 412/428, and retry flow

6. Schema/client alignment

- [x] Confirm generated endpoints exist and compile:
  - [x] `api.job_rest_jobs_update` (PUT with full envelope)
  - [x] `api.job_rest_jobs_partial_update` (PATCH with partial envelope)
  - [x] `api.job_rest_jobs_undo_change_create` (POST with `JobUndoRequest`)

Post-merge

- [ ] Phase 2 card: extend to other job fields/tabs using the same builder/service
