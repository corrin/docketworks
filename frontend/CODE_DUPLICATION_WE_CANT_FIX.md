# Code Duplication We Can't Fix

This document tracks all locations where job fields are enumerated. When adding a new job field,
**all of these locations must be updated**.

Last updated: 2025-12-02 (added `price_cap`)

---

## Checklist for Adding a New Job Field

### 1. job.service.ts - Nullable Keys Set

**Lines ~25-34**

If the field is nullable (can be null/empty), add it to `nullableKeys`:

```typescript
const nullableKeys = new Set([
  'description',
  'order_number',
  'notes',
  'delivery_date',
  'quote_acceptance_date',
  'price_cap',
  'contact_name',
])
```

### 2. job.service.ts - Before Values Switch Statement

**Lines ~59-104**

Add a case for extracting the field's "before" value from the server response:

```typescript
case 'price_cap':
  beforeValues[field] = currentJob.data.job.price_cap
  break
```

### 3. jobs.ts (Store) - jobToHeader() Function

**Lines ~329-346**

If the field should be in the header, add it to the return object:

```typescript
const jobToHeader = (job: Job): JobHeaderResponse => {
  return {
    // ... existing fields ...
    price_cap: job.price_cap ?? null,
  }
}
```

### 4. jobs.ts (Store) - commitJobBasicInfoFromServer()

**Lines ~228-270**

If it's a "basic info" field (description, delivery_date, order_number, notes), add handling here.

### 5. jobs.ts (Store) - setDetailedJob() Field Preservation

**Lines ~84-88**

If the field should be preserved when merging job details:

```typescript
description: jobDetail.job.description ?? existingJob.job.description,
```

### 6. JobSettingsTab.vue - Default Job Data Initialization

**Lines ~574-595**

Add the field to the default job data object:

```typescript
const defaultJobData = {
  // ... existing fields ...
  price_cap: null,
}
```

### 7. JobSettingsTab.vue - Job Data Snapshot

**Lines ~607-620**

Add the field when creating the job data snapshot from server data:

```typescript
const jobDataSnapshot = {
  // ... existing fields ...
  price_cap: newJobData.price_cap ?? null,
}
```

### 8. JobSettingsTab.vue - Server Baseline

**Lines ~632-643**

Add the field to the server baseline for delta tracking:

```typescript
serverBaseline.value = {
  // ... existing fields ...
  price_cap: localJobData.value.price_cap ?? null,
}
```

### 9. JobSettingsTab.vue - getSnapshot() Function

**Lines ~996-1020**

Add the field to the autosave snapshot:

```typescript
getSnapshot: () => {
  return {
    // ... existing fields ...
    price_cap: data.price_cap ?? null,
  }
}
```

### 10. JobSettingsTab.vue - applyPayloadToBaseline()

**Lines ~1084-1125**

Add handling for applying the field to the baseline:

```typescript
if ('price_cap' in payload) next.price_cap = (payload.price_cap as number | null) ?? null
```

### 11. JobSettingsTab.vue - Touched Keys Handling (Server Response)

**Lines ~1139-1226**

Add handling when the field is touched and server responds:

```typescript
if (touchedKeys.includes('price_cap')) {
  nextBaseline.price_cap = serverJobDetail.price_cap ?? null
  localJobData.value.price_cap = serverJobDetail.price_cap ?? null
  headerPatch.price_cap = serverJobDetail.price_cap ?? null
}
```

### 12. JobSettingsTab.vue - Touched Keys Handling (Fallback)

**Lines ~1234-1331**

Add fallback handling when server detail is not available:

```typescript
if (touchedKeys.includes('price_cap')) {
  const priceCapVal = partialPayload.price_cap as number | null
  nextBaseline.price_cap = priceCapVal
  localJobData.value.price_cap = priceCapVal
  headerPatch.price_cap = priceCapVal
}
```

### 13. JobSettingsTab.vue - Header Sync Watcher

**Lines ~817-827**

If the field is in the header, add it to the sync from store:

```typescript
localJobData.value.price_cap = newHeader.price_cap ?? null
```

### 14. JobSettingsTab.vue - Input Handler (if user-editable)

For string fields, add to `handleFieldInput()` (~lines 513-537):

```typescript
} else if (field === 'my_new_field') {
  localJobData.value.my_new_field = newValue
}
```

For numeric nullable fields, create a dedicated handler like `handlePriceCapInput()`.

### 15. JobSettingsTab.vue - Template UI

Add the actual input field in the template section.

---

## Field Categories

### Header Fields (JobHeaderResponse)

These appear in job list views and need fast access:

- job_id, job_number, name, client, status
- pricing_methodology, speed_quality_tradeoff, price_cap
- quoted, fully_invoiced, paid, quote_acceptance_date
- rejected_flag

### Basic Info Fields (JobBasicInformationResponse)

Loaded separately to avoid autosave conflicts:

- description, delivery_date, order_number, notes

### Contact Fields

Managed through separate endpoint:

- contact_id, contact_name

---

## Why This Duplication Exists

The frontend has multiple layers that each need to know about job fields:

1. **Service Layer** (`job.service.ts`) - Handles API communication and field normalization
2. **Store Layer** (`jobs.ts`) - Manages state and type conversions
3. **Component Layer** (`JobSettingsTab.vue`) - Handles UI state, autosave, and optimistic updates

Each layer has its own concerns:

- Services need to know which fields are nullable for API serialization
- Stores need to know how to convert between different job representations
- Components need to track field changes for autosave and handle server responses

TypeScript's type system catches some issues, but runtime field handling (switch statements,
if-else chains) must be manually maintained.

---

## Testing New Fields

After adding a new field, verify:

1. [ ] Field appears in the UI
2. [ ] Changes trigger autosave
3. [ ] Value persists after page refresh
4. [ ] Value syncs correctly when edited elsewhere (multi-user)
5. [ ] Concurrency conflicts are handled properly
6. [ ] Field appears in job headers if applicable
