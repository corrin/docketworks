# Job Autosave – Functional and Non-Functional Requirements

## Context

- Autosave for the Job entity, inspired by useTimesheetAutosave()
- Integration in the src/components/job/JobSettingsTab.vue and src/components/job/JobWorkflowTab.vue tabs
- Persistence via jobService.updateJob()

## Functional Requirements

- Fields covered:
- Job ID (prerequisite for saving)
- name
- description
- client_id, client_name
- contact_id, contact_name
- pricing_methodology
- notes
- job_status
- delivery_date
- Uniform debounce: 500 ms
- Flush on input/select/editor blur
- Single-flight per Job: only 1 request in flight
- Coalescence of rapid changes into a single payload
- Deduplication by field key (last value wins within the window)
- No-op guard: skip saves without effective changes (after normalization)
- In-memory retry:
- attempts: 3
- exponential backoff: 500ms, 1000ms, 2000ms
- jitter: yes
- abort retry for 400/422
- Offline: immediate failure (no persistent queue)
- Cancel/Flush:
- beforeunload: synchronous flush if possible
- visibility hidden: flush when hidden
- route leave: flush before navigation
- Optimism: apply local patch; Rollback on error
- Conflicts (optional, via adapter):
- If updated_at or version token exists, detect conflict and flag
- No support: last-write-wins
- Save state:
- isSaving, lastSavedAt, error
- Discreet UI: Saving… / Saved at HH:mm:ss / Error with Retry

## Non-Functional Requirements

- Performance:
- Granular watchers per field
- Avoid observing entire objects
- Normalization reduces cosmetic diffs
- Strict typing in composable and integration
- Tree-shakeable
- Isolated for testing (no store dependency)
- Zero new dependencies
- No feature flags/telemetry at this time
- Rules compliance:
- No creating local Job data schemas
- Reuse types from src/api/generated/api.ts when necessary (no adapter)
- Do not request static enums from the backend (status choices already exist in the Frontend)

## A11y and Inline Header UX (future)

- Hover/focus to reveal controls
- Enter confirms, Esc cancels, blur flushes
- Focus visible; labels for SR
- Identical appearance when idle (no visible editors)
- Discreet save indicator in the header

## Logging

- DEV: debugLog at key points
- PROD: silent (no telemetry)
