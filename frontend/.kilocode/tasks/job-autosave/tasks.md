# Job Autosave – Execution Plan and Acceptance Criteria

## Ordered Steps

1. Create src/composables/useJobAutosave.ts

- Implement the createJobAutosave factory with the specified API
- Implement buffering by key, debounce, single-flight, retry, optimistic with rollback
- Binding helpers: beforeunload, visibilitychange, route-leave
- Criteria:
- queueChange and queueChanges coalesce and de-dupe by key
- flush ignores no-op and respects single-flight
- retry with 3 attempts and jitter
- offline immediate failure

2. Integrate into src/components/job/JobSettingsTab.vue

- Add granular watchers for name, description, pricing_methodology, notes, client_id/name, contact_id/name
- Implement the isInitializing guard to suppress saves on load
- Remove saveSettings() button
- Criteria:
- Changing client_id resets contact_id/name in the same patch
- Blur forces flush
- Visible but discreet status indicator (saving/saved/error)

3. Integrate into src/components/job/JobWorkflowTab.vue

- Watchers for job_status and delivery_date
- Guard isInitializing
- Remove saveWorkflow() button
- Criteria:
- Select/date trigger flush on blur
- Status indicator consistent with SettingsTab

4. Expose saving/saved/error UI in both tabs

- Discreet locations in the card header or tab title
- Criteria:
- isSaving → Saving… text
- lastSavedAt → Saved at HH:mm:ss
- error → small inline with Retry that calls flush

5. Unit tests in tests/unit/composables/useJobAutosave.spec.ts

- Cover: dedupe by key, coalesce, retry, no-op, optimistic+rollback
- Criteria:
- Simulate saveAdapter with 5xx and 422 failures
- Verify calls and states

6. Component test: name change with coalesce + flush

- On a minimal version of SettingsTab built in test
- Criteria:
- Multiple quick keystrokes → 1 send after debounce
- Blur → Immediate flush

7. Header blueprint (no visual implementation)

- Create docs/job-header-inline-blueprint.md with component specifications and interactions
- Criteria:
- Unified data flow via a single autosave instance in JobView
- Global save indicator in the header

8. Final review

- No-op on data refresh (watchers respect isInitializing)
- Blur flush on all Fields
- Immediate offline error, no retry
- Optimistic rollback on persistence error
