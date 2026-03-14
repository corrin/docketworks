# Job Settings Autosave Reliability Plan

## Context & Observed Issues

- Rapid edits in `JobSettingsTab.vue` trigger multiple autosave flushes while the previous PATCH is still in flight.
- `handleFieldInput` syncs changes straight into `jobsStore.updateBasicInfo`, and the store watcher writes those values back into `originalJobData`. As a result, the next delta is generated with a "before" snapshot that already contains the optimistic value instead of the last server-acknowledged state.
- When the backend compares the client checksum with the real row, the mismatch raises a 412 error. In the same burst of edits, other fields can be skipped entirely because the diffing logic believes nothing changed.
- Our current queue keeps a single debounce buffer, but it does not rebuild the outgoing patch after the preceding request finishes; it merely reuses whatever was buffered earlier, which may no longer align with the newest local state or ETag.

## Goals (Reliability = Must-have)

- Maintain an authoritative, server-sourced baseline that is never overwritten by optimistic or draft values.
- Guarantee single-flight sequencing so every PATCH is built after the latest response (or reload) has updated the baseline and ETag.
- Make delta envelopes deterministic even under rapid edits, retries, or conflict recovery.
- Preserve responsive UX (fields stay reactive) without leaking draft values into the baseline.
- Provide clear instrumentation and tests that cover the previously failing flows.

## Constraints & Considerations

- We must stay compatible with the backend `JobDeltaEnvelope` contract (field list, checksum, ETag).
- Any refactor must coexist with existing store consumers (other views read from `jobsStore.basicInfo` and `jobsStore.updateDetailedJob`).
- Conflict recovery already uses `onConcurrencyRetry`; new logic should hook into the same channel instead of adding parallel mechanisms.
- Plan for incremental rollout: keep the surface small enough to ship iteratively, but ensure each step maintains correctness.

## Workstreams & Deliverables

### 1. Snapshot & Delta Fidelity

- **Introduce dual snapshots**: keep `serverBaselineRef` (last ACKed server state) alongside `draftStateRef` (what the form shows). Replace usages of `originalJobData` with an explicit baseline structure consumed only by the autosave queue and delta builder.
- **Isolate store writes**: route `handleFieldInput` through a lightweight draft cache (or scoped store channel) so that `jobsStore.updateBasicInfo` only reflects server-confirmed data. Where immediate UI updates are required, patch the local ref (`draftStateRef`) directly without touching the baseline.
- **Baseline updates on ACK**: after a successful PATCH, refresh `serverBaselineRef` using the actual response payload (include regenerated ETag) rather than the just-sent patch, so we capture server-side normalizations or defaults.
- **Failure handling**: when a PATCH fails (network, 4xx, 5xx), roll back draft state to the unchanged `serverBaselineRef`, preserving user input elsewhere via toast guidance where appropriate.

### 2. Autosave Queue Discipline & Recovery

- **Single-flight enforcement**: ensure `attemptFlush` always re-reads `serverBaselineRef` and the latest draft state when composing a payload post-flight. Replace the stored raw `sendingPatch` approach with a `rebuildPatchAfterFlight()` helper that diff-checks fresh values before dispatch.
- **Explicit queue state machine**: track queue status (`idle`, `scheduled`, `inFlight`, `recovering`) to avoid hidden booleans (`pendingAfterFlight`, `retryLatched`). This will simplify reasoning about overlapping events and retries.
- **ETag lifecycle**: pull ETag updates from the PATCH response headers (or the follow-up GET) and push them into `useJobETags` before the next send to keep the token fresh.
- **Conflict handling with manual retry**: on 412/428, fetch the latest job header, repopulate `serverBaselineRef`, and surface the refreshed state plus retry affordance. Do not automatically replay the pending patch; wait for the user to trigger the next attempt after they see the updated data.

### 3. Reactive UI & Store Synchronisation

- **Form reactivity**: refactor field watchers to read from `draftStateRef`, emitting `queueChange` only after a debounce tied to user stop-typing; this reduces churn and makes it easier to pause saves while the user is actively editing.
- **Scoped store sync**: push server-confirmed values into `jobsStore` via a dedicated `commitJobBasicInfoFromServer(jobId, payload)` helper so that other views stay accurate without depending on draft states.
- **Preserve editor markup**: ensure diffing logic respects full HTML for description/notes so editors can round-trip styling without normalization losses.

### 4. Instrumentation, Testing, and QA

- **Lightweight telemetry**: keep existing `debugLog` instrumentation (flagged) to aid manual debugging during rollout.
- **QA checklist**: document manual steps (rich text edit, order number swap, intentional conflict) in `docs/jobview-delta-control-guide.md` so support can verify after deployment. Automated tests are out of scope for this effort.

## Agreed Constraints & Decisions

- Continue to rely on the existing follow-up GET to refresh the ETag and authoritative data before a manual retry.
- Only `JobView.vue` depends on header field syncing; changes can focus on `JobSettingsTab.vue` without broader refactors.
- Keep the current debounce durations; stability will come from queue discipline rather than longer delays.
