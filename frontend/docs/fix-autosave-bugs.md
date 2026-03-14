# Fix Autosave Bugs & Standardize Patterns

## The Problem

We discovered two autosave bugs while writing e2e tests:

### Bug 1: JobView.vue - Vue Composition API Violation

In `JobView.vue` line 511, `useJobHeaderAutosave(h)` is called inside a watcher callback:

```typescript
watch(
  jobHeader,
  (h) => {
    if (!h) return
    if (!headerAutosave) {
      headerAutosave = useJobHeaderAutosave(h) // <-- WRONG: called in watcher
    }
    // ...
  },
  { immediate: true },
)
```

**Why this is wrong:** Vue composables that use `useRouter()`, `onMounted()`, `onUnmounted()`, or `inject()` must be called synchronously during `setup()`. Watcher callbacks run asynchronously, so Vue's context is lost.

### Bug 2: JobSettingsTab.vue - Mixed Patterns Causing Double-Queuing

The codebase mixes two patterns:

- **Handlers** (`handleFieldInput`) update `localJobData` AND call `autosave.queueChange()`
- **Watchers** on `localJobData.value.name` etc. ALSO call `enqueueIfNotInitializing()`

This causes double-queueing when both fire for the same edit. The guards (`isSyncingFromStore`, `isInitializing`) are inconsistent across fields, making behaviour unpredictable.

---

## Autosave Rules (The Fix)

**Exactly one autosave path per field:**

```
user edits → template event → handler → autosave.queueChange(...)
```

1. **Handlers own "user → queue"**: `handleFieldInput` updates `localJobData` and queues the autosave.

2. **Watchers own "store → local" only**: Watchers copy data from the store into `localJobData`. They NEVER queue.

3. **All queuing from watchers must be removed.**

---

## Part 1: Fix JobView.vue Composable

### Changes to `useJobHeaderAutosave.ts`

1. Change signature to accept nullable ref only:

   ```typescript
   export function useJobHeaderAutosave(headerRef: Ref<JobHeaderResponse | null>)
   ```

2. Add one-time initialization watcher. Move all header-dependent initialisation (`localHeader`, `originalHeader`, `deltaQueue`, `createJobAutosave`) into the watcher:

   ```typescript
   const isInitialized = ref(false)
   let localHeader: Ref<JobHeaderResponse> | null = null
   let originalHeader: Ref<JobHeaderResponse> | null = null
   let deltaQueue: ReturnType<typeof useJobDeltaQueue> | null = null
   let autosave: ReturnType<typeof createJobAutosave> | null = null

   watch(
     headerRef,
     (header) => {
       if (!header || isInitialized.value) return
       // One-time init using header
       localHeader = ref(header)
       originalHeader = ref(header)
       deltaQueue = useJobDeltaQueue(header.job_id)
       autosave = createJobAutosave({ jobId: header.job_id, ... })
       isInitialized.value = true
     },
     { immediate: true },
   )
   ```

3. Add null guards in handlers as last line of defence:

   ```typescript
   const handleNameUpdate = (name: string) => {
     if (!headerRef.value) return
     enqueue('name', name)
   }
   ```

4. Keep `onMounted`/`onUnmounted` at top level (they'll work now since called in setup).

### Changes to `JobView.vue`

1. Call composable once in setup:

   ```typescript
   // Remove: let headerAutosave: ... | null = null
   // Add:
   const headerAutosave = useJobHeaderAutosave(jobHeader)
   ```

2. Remove the composable initialization from the watcher (lines 510-512).

3. Keep the watcher for syncing local UI values only.

---

## Part 2: Standardize JobSettingsTab Patterns

### Handler Guard

`handleFieldInput` uses a single, clear condition for queuing:

```typescript
if (!isInitializing.value && !isHydratingBasicInfo.value && !isSyncingFromStore.value) {
  autosave.queueChange(field, newValue)
}
```

Note: `isSyncingFromStore` is only set inside store→local watchers, not in handlers.

### Field-by-Field Changes

#### name, order_number (text inputs)

**Template:** Already have `@input="handleFieldInput(...)"` - confirm present.

**Watcher:** Remove queuing. If store→local sync needed, watcher should only do:

```typescript
watch(
  () => jobStore.job?.name,
  (v) => {
    isSyncingFromStore.value = true
    localJobData.value.name = v ?? ''
    isSyncingFromStore.value = false
  },
)
```

#### pricing_methodology, speed_quality_tradeoff (selects)

**Template:** Add `@change` handler:

```vue
@change="handleFieldInput('pricing_methodology', ($event.target as HTMLSelectElement).value)"
```

**Watcher:** Remove queuing entirely. Watchers only handle store→local sync.

#### client

**Handler:** Update `confirmClientChange` to both update `localJobData.client` AND call `autosave.queueChange`:

```typescript
const confirmClientChange = () => {
  // ... existing validation ...
  localJobData.value.client = { id: newClientId.value, name: selectedNewClient.value.name }
  // Add queuing:
  if (!isInitializing.value && !isHydratingBasicInfo.value && !isSyncingFromStore.value) {
    autosave.queueChange('client_id', newClientId.value)
  }
  // ... rest of function ...
}
```

**Watcher:** Remove queuing. Keep only store→local sync.

### Template Changes Summary

| Field                  | Current             | Change Needed                         |
| ---------------------- | ------------------- | ------------------------------------- |
| name                   | Has @input          | None (confirm present)                |
| order_number           | Has @input          | None (confirm present)                |
| pricing_methodology    | @blur only          | Add `@change="handleFieldInput(...)"` |
| speed_quality_tradeoff | @blur only          | Add `@change="handleFieldInput(...)"` |
| client                 | confirmClientChange | Add `autosave.queueChange` call       |

### Watcher Changes Summary

| Watcher                                     | Current                          | Change         |
| ------------------------------------------- | -------------------------------- | -------------- |
| `localJobData.value.name`                   | Calls `enqueueIfNotInitializing` | Remove queuing |
| `localJobData.value.order_number`           | Calls `enqueueIfNotInitializing` | Remove queuing |
| `localJobData.value.pricing_methodology`    | Calls `enqueueIfNotInitializing` | Remove queuing |
| `localJobData.value.speed_quality_tradeoff` | Calls `enqueueIfNotInitializing` | Remove queuing |
| `localJobData.value.client`                 | Calls `enqueueIfNotInitializing` | Remove queuing |

---

## When Adding a New Field (Checklist)

For any new field in JobSettingsTab:

1. **Template**

   - Text input:
     - `@input="handleFieldInput('field_name', ($event.target as HTMLInputElement).value)"`
   - Select:
     - `@change="handleFieldInput('field_name', ($event.target as HTMLSelectElement).value)"`

2. **Handler**

   - Do **not** add any new autosave logic.
   - `handleFieldInput` is the **only** place that calls `autosave.queueChange(...)`
     (behind the `!isInitializing && !isHydratingBasicInfo && !isSyncingFromStore` guard).

3. **Watchers**
   - If you need store→local sync, add a watcher that:
     - reads from `jobStore.job?.field_name`
     - sets `isSyncingFromStore` while writing to `localJobData.field_name`
   - Watchers must never call `autosave.queueChange`, `enqueueIfNotInitializing`, or any autosave function.

---

## Files to Modify

1. `src/composables/useJobHeaderAutosave.ts` - Accept nullable ref, add one-time init watcher
2. `src/views/JobView.vue` - Move composable call to setup, remove watcher-based init
3. `src/components/job/JobSettingsTab.vue` - Remove queuing from watchers, add missing handlers

## Testing

```bash
npx playwright test tests/edit-job.spec.ts
```

Verify:

- [ ] No Vue warnings in browser console
- [ ] Job name saves when edited in JobSettingsTab
- [ ] All other fields save correctly
- [ ] No duplicate saves (check network tab)
