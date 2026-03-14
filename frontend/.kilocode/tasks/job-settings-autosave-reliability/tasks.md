# Job Settings Autosave Reliability – Task List

Use this checklist to track the hardening work. Keep manual retry behaviour, preserve rich text markup, and lean on QA docs instead of automated tests.

- [ ] **Snapshot separation**

  - [ ] Introduce a `serverBaselineRef` that mirrors the most recent server payload (including normalized nulls and ETag reference).
  - [ ] Keep `draftStateRef` (or reuse `localJobData`) for UI binding without mutating the baseline.
  - [ ] Replace existing `originalJobData` usages with the new baseline accessors inside `createJobAutosave` hooks and payload builders.

- [ ] **Baseline refresh on success/failure**

  - [ ] After successful PATCH responses, refresh the baseline from the server response (or follow-up GET) before allowing the next flush.
  - [ ] When a PATCH fails, roll back draft fields to the baseline and retain user input for review where appropriate.

- [ ] **Autosave queue discipline**

  - [ ] Ensure only one PATCH is in flight per job; hold subsequent flushes until the previous response updates the baseline/ETag.
  - [ ] Rebuild outgoing patches from the latest baseline + draft state right before sending, rather than reusing stale buffers.
  - [ ] Keep the manual "Retry" button flow: on 412/428, refresh the baseline via GET, update the UI, and wait for user-triggered retry (no auto requeue).

- [ ] **Store synchronisation**

  - [ ] Route `jobsStore.updateBasicInfo` (and related helpers) to write server-confirmed data only, avoiding optimism from draft edits.
  - [ ] Provide a helper such as `commitJobBasicInfoFromServer(jobId, payload)` so other views stay in sync.
  - [ ] Verify `JobView.vue` continues to receive updated header fields without relying on draft values.

- [ ] **ETag lifecycle**

  - [ ] Capture updated ETags from the PATCH response (headers or follow-up GET) and push them into `useJobETags` before the next flush.

- [ ] **Documentation & QA**

  - [ ] Expand `docs/jobview-delta-control-guide.md` with a manual QA checklist (rapid edits, order-number + notes conflict scenario, manual retry flow).
  - [ ] Note the continued requirement for the follow-up GET before retries to guarantee the user sees the latest data.

- [ ] **Debug instrumentation (optional)**
  - [ ] Keep `debugLog` hooks (behind feature flag) around queue transitions and checksum inputs to aid troubleshooting during rollout.
