# Job Creation Quote Tab Redirection and Automatic Cost Line Copy - Architectural Plan

## Executive Summary

This plan outlines the modification of job creation behavior to automatically redirect users to the quote tab instead of the actual tab after job creation, automatically copy estimate cost lines to the quote cost set, and remove the manual "Copy from Estimate" button.

## Current State Analysis

### Job Creation Flow

1. User fills out job creation form in `JobCreateView.vue`
2. Form submission creates job via `jobService.createJob()`
3. Cost lines are created in 'estimate' set (materials, workshop time, office time)
4. User is redirected to `job-edit` route with `router.push({ name: 'job-edit', params: { id: job_id } })`

### Tab Management

- `JobView.vue` uses `useJobTabs('actual')` which defaults to 'actual' tab
- Tabs are managed by `JobViewTabs.vue` component
- Available tabs: estimate, quote, actual, costAnalysis, jobSettings, history, attachments, quotingChat

### Cost Line Management

- Cost lines are stored in CostSets by kind: 'estimate', 'quote', 'actual'
- Manual copy functionality exists in `JobQuoteTab.vue` via `onCopyFromEstimate()` function
- Copy process: fetches estimate CostSet, deletes existing quote lines, creates new quote lines from estimate data

### Manual Copy Button

- Located in `JobQuoteTab.vue` template (line 21-29)
- Button is enabled when `hasEstimateData.value` is true
- Triggers `onCopyFromEstimate()` which performs the copy operation

## Proposed Changes

### 1. Automatic Cost Line Copy During Job Creation

**Location:** `src/views/JobCreateView.vue`

**Current Code (lines 514-551):**

```typescript
const result = await jobService.createJob(formData.value)

if (result.success && result.job_id) {
  const job_id = result.job_id
  try {
    await costlineService.createCostLine(job_id, 'estimate', {
      kind: 'material',
      desc: 'Estimated materials',
      quantity: 1,
      unit_cost: formData.value.estimatedMaterials!,
      unit_rev:
        formData.value.estimatedMaterials! *
        (1 + companyDefaultsStore.companyDefaults?.materials_markup),
    })
  } catch (error: unknown) {
    toast.error((error as Error).message)
    debugLog('Failed to create material cost line:', error)
  }
  // ... additional estimate cost lines ...
}
```

**Proposed Code:**

```typescript
const result = await jobService.createJob(formData.value)

if (result.success && result.job_id) {
  const job_id = result.job_id

  // Create estimate cost lines (existing logic)
  const estimateLines = []
  try {
    const materialLine = await costlineService.createCostLine(job_id, 'estimate', {
      kind: 'material',
      desc: 'Estimated materials',
      quantity: 1,
      unit_cost: formData.value.estimatedMaterials!,
      unit_rev:
        formData.value.estimatedMaterials! *
        (1 + companyDefaultsStore.companyDefaults?.materials_markup),
    })
    estimateLines.push(materialLine)
  } catch (error: unknown) {
    toast.error((error as Error).message)
    debugLog('Failed to create material cost line:', error)
  }

  // ... create other estimate lines and collect them ...

  // Automatically copy estimate lines to quote set
  if (estimateLines.length > 0) {
    try {
      for (const estimateLine of estimateLines) {
        await costlineService.createCostLine(job_id, 'quote', {
          kind: estimateLine.kind,
          desc: estimateLine.desc,
          quantity: estimateLine.quantity,
          unit_cost: estimateLine.unit_cost,
          unit_rev: estimateLine.unit_rev,
          ext_refs: estimateLine.ext_refs || {},
          meta: estimateLine.meta || {},
        })
      }
      debugLog('Successfully copied estimate lines to quote set')
    } catch (error: unknown) {
      toast.error('Job created but failed to copy cost lines to quote')
      debugLog('Failed to copy estimate lines to quote:', error)
    }
  }
}
```

### 2. Tab Redirection After Job Creation

**Location:** `src/views/JobCreateView.vue`

**Current Code (line 554):**

```typescript
router.push({ name: 'job-edit', params: { id: job_id } })
```

**Proposed Code:**

```typescript
router.push({
  name: 'job-edit',
  params: { id: job_id },
  query: { tab: 'quote' },
})
```

**Location:** `src/views/JobView.vue`

**Current Code (line 357):**

```typescript
const { activeTab, setTab } = useJobTabs('actual')
```

**Proposed Code:**

```typescript
const route = useRoute()
const defaultTab = (route.query.tab as JobTabKey) || 'actual'
const { activeTab, setTab } = useJobTabs(defaultTab)
```

**Location:** `src/composables/useJobTabs.ts`

**Current Code:**

```typescript
export function useJobTabs(initialTab: JobTabKey = 'estimate') {
  const activeTab = ref<JobTabKey>(initialTab)
  // ...
}
```

**Proposed Code:**

```typescript
export function useJobTabs(initialTab: JobTabKey = 'actual') {
  const activeTab = ref<JobTabKey>(initialTab)
  // ...
}
```

### 3. Remove Manual Copy Button

**Location:** `src/components/job/JobQuoteTab.vue`

**Current Code (lines 19-30):**

```vue
<div class="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
  <h3 class="text-lg font-semibold text-gray-900">Quote Details</h3>
  <button
    class="inline-flex items-center justify-center h-9 px-3 rounded-md bg-blue-600 text-white border border-blue-700 text-sm font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
    style="min-width: 0"
    @click="onCopyFromEstimate"
    :disabled="isLoading || !hasEstimateData"
    :title="'Copy from Estimate'"
  >
    <Copy class="w-4 h-4 mr-1" /> Copy from Estimate
  </button>
</div>
```

**Proposed Code:**

```vue
<div class="px-4 py-3 border-b border-slate-200">
  <h3 class="text-lg font-semibold text-gray-900">Quote Details</h3>
</div>
```

## Implementation Steps

### Phase 1: Core Functionality

1. **Modify Job Creation Flow**

   - Update `JobCreateView.vue` to collect created estimate lines
   - Add automatic copy logic to quote set
   - Handle errors gracefully (job creation succeeds even if copy fails)

2. **Implement Tab Redirection**
   - Modify router.push in `JobCreateView.vue` to include tab query parameter
   - Update `JobView.vue` to read tab from query parameters
   - Adjust `useJobTabs` default to 'actual' to maintain backward compatibility

### Phase 2: Remove Manual Copy Button

3. **Remove Manual Copy Button**
   - Remove the copy button from `JobQuoteTab.vue` template
   - Remove related logic and imports if no longer needed

## Acceptance Criteria

### Functional Requirements

- [ ] After job creation, user is automatically redirected to the quote tab
- [ ] Estimate cost lines are automatically copied to quote cost set during job creation
- [ ] Manual copy button is completely removed
- [ ] Job creation still succeeds even if automatic copy fails
- [ ] Existing functionality for other tabs remains unchanged

### Error Handling

- [ ] Clear error messages if automatic copy fails
- [ ] Job creation process continues even if copy operation fails
- [ ] Debug logging for troubleshooting copy operations

### User Experience

- [ ] Seamless transition to quote tab after job creation
- [ ] No duplicate cost lines created
- [ ] Clear indication when quote data is pre-populated
- [ ] Backward compatibility for existing job URLs without tab parameter

### Technical Requirements

- [ ] TypeScript types maintained throughout
- [ ] API calls follow existing patterns
- [ ] Error handling consistent with application standards
- [ ] Performance impact minimized (copy happens during creation, not blocking UI)

## Conclusion

This architectural plan provides a clear path to implement the requested job creation behavior modifications. The changes are focused, backward-compatible, and follow existing application patterns. The automatic copy functionality eliminates the need for manual intervention while the tab redirection improves user workflow efficiency.
