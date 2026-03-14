# Design Plan – Job Autosave

## Mermaid – Pipeline

```mermaid
TD flowchart
A[User edits field] --> B[queueChange]
B --> C[Debounce 500ms]
C --> D{isSaving?}
D -- yes --> E[Mark pendingAfterFlight]
D -- no --> F[Compute diff normalized]
F --> G{Patch empty?}
G -- yes --> H[No-op, exit]
G -- no --> I[Optimistic apply]
I --> J[saveAdapter with retry]
J -- success --> K[Update lastSavedAt, clear error]
J -- error --> L[Rollback, set error]
K --> M{pendingAfterFlight?}
M -- yes --> N[Reset flag and attemptFlush]
M -- no --> O[Done]
L --> O[Done]

```

## Internal Structure

- changeBuffer: Map of fieldKey → normalized value
- debounceTimer: unique per Job
- isSaving: Boolean ref
- pendingAfterFlight: Boolean
- inFlightToken: increments with each send
- Requeue rules: if pendingAfterFlight=true after completing a run, run attemptFlush again

## Normalization and Equality

- string: trim + collapse whitespace
- enum: case-insensitive; ensure snake_case
- date: YYYY-MM-DD
- id: compare as string
- dependencies:
- client_id changed → send contact_id=null and contact_name=null
- contact\_\* requires client_id present

## Field → key mapping

- name → name
- description → description
- client → client_id, client_name
- contact → contact_id, contact_name
- pricing method → pricing_methodology
- notes → notes
- status → job_status
- delivery date → delivery_date

## Suppress redundant saves

- isInitializing: true during prop loading
- watchers abort when isInitializing
- normalized comparison prevents cosmetic diffs
- no-op guard before sending

## Header blueprint

- Components
- JobHeaderEditable.vue
- Props: job, autosaveState { isSaving, lastSavedAt, error }, UI enums
- Emits: fieldChange { key, value, meta }
- Internal slots for inline editors
- InlineTextEdit.vue
- Props: value, placeholder, aria-label
- Enter confirms, Esc cancels, blur flush
- InlineSelectEdit.vue
- Props: value, options, aria-label
- InlineClientEdit.vue
- ClientLookup adapter with popover; When selecting a client, emit { client_id, client_name } and clear the contact.
- Integration with JobView
- Instantiate createJobAutosave only once in src/views/JobView.vue
- Pass handlers to the header and tabs
- Global indicator:
- Saving…
- Saved at HH:mm:ss
- Error with Retry → flush
- A11y
- Descriptive aria-labels
- Consistent focus rings
- No visual change when idle

---

1. Header Blueprint and Unified Integration

Where to instantiate

- Create a single instance of autosave in the scope of JobView src/views/JobView.vue, with:
- jobId derived from the route
- getSnapshot reading the Job's unified reactive source (preferably from the store + local overlay)
- applyOptimistic/rollbackOptimistic updating the local overlay JobView, reflected in tabs via props
- saveAdapter routing to jobService.updateJob()

Component composition

- JobHeaderEditable.vue
- Receives job and autosaveState (isSaving, lastSavedAt, error)
- Emits fieldChange { key, value } to JobView
- JobView calls autosave.queueChange(key, value) and flushes on blur/enter
- For client: on selection, emits { client_id, client_name }; JobView calls autosave.queueChanges({ client_id, client_name, contact_id: null, contact_name: null }) and flushes immediately
- Tabs
- Settings and Workflow consume data from the JobView or shared instance; Watchers pass patches to the same autosave instance (avoids collision)
- Global indicator
- Rendered in the header on desktop and mobile
- States:
- isSaving: Saving… text
- error: error icon + Retry button → autosave.flush('retry-click')
- idle: Saved at HH:mm:ss

UX Rules

- Hover/focus: reveals inline controls without changing the default layout
- Enter: confirms current change with a flush
- Esc: cancels and restores the previous value (does not queue the patch)
- Blur: flush

2. Error and Conflict Scenarios

Error Types

- Offline: navigator.onLine=false → immediate failure, rollback, display "No Connection" error
- 400/422 validation: no retry, rollback, display short message; error field remains with its previous value
- 5xx/network: retry with backoff; After overflowing attempts, rollback, and "Temporary failure" error
- Conflict:
- If the adapter identifies a conflict via outdated updated_at, set conflict=true; instruct the UI to display a warning to reload the Job
- Without updated_at, adopt last-write-wins; if necessary, plan future improvements with ETag/If-Match

1. Direct references in existing code

- Algorithm inspiration: useTimesheetAutosave()
- Persistence: jobService.updateJob()
- Display status loading: src/services/job.service.ts and src/components/job/JobWorkflowTab.vue
- Buttons to remove: saveSettings() and saveWorkflow()

2. Summary of textual deliverables included in this response

- Specification: The end of the composable and flow
- List of watchers per tab + guards and flush in blur
- Detailed adapter for jobService.updateJob()
- Complete content ready for the files:
- .kilocode/tasks/job-autosave/requirements.md
- .kilocode/tasks/job-autosave/tasks.md
- .kilocode/tasks/job-autosave/design_plan.md
- Header blueprint with unified pipeline and global indicator
