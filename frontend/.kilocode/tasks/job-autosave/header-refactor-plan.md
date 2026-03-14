# JobView Header Inline Editing Refactor Plan

## Overview

Plan to refactor the [`JobView.vue`](src/views/JobView.vue) header to support inline editing of key job fields, integrated with the existing autosave system.

## Current State

The header currently displays job information as static text:

- Job name (lines 16-17, 43-44)
- Job number and client name (lines 28, 55)
- Quote acceptance warning badge

## Proposed Features

### 1. Inline Editable Job Name

- **Trigger**: Click on job name or hover + edit icon
- **Component**: Custom `InlineEditText.vue`
- **Behavior**: Transform to input field with autosave
- **Validation**: Required field, min 1 character

### 2. Inline Editable Client Selection

- **Trigger**: Click on client name or hover + edit icon
- **Component**: Custom `InlineEditClient.vue` wrapping [`ClientLookup`](src/components/ClientLookup.vue)
- **Behavior**: Transform to client lookup component
- **Dependencies**: Clears contact when client changes

### 3. Inline Editable Job Status Badge

- **Trigger**: Click on status area (new feature)
- **Component**: Custom `InlineEditSelect.vue`
- **Options**: Use existing [`JOB_STATUS_CHOICES`](src/constants/job-status.ts)
- **Visual**: Status badge with dropdown on edit

## Technical Implementation

### Phase 1: Create Base Components

#### `InlineEditText.vue`

```vue
<template>
  <div class="inline-edit-text">
    <div v-if="!isEditing" @click="startEdit" class="cursor-pointer hover:bg-gray-50 rounded px-1">
      <span>{{ displayValue }}</span>
      <PencilIcon class="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100" />
    </div>
    <input
      v-else
      ref="inputRef"
      v-model="editValue"
      @blur="handleBlur"
      @keydown.enter="confirm"
      @keydown.escape="cancel"
      class="border rounded px-2 py-1"
    />
  </div>
</template>
```

#### `InlineEditClient.vue`

```vue
<template>
  <div class="inline-edit-client">
    <div v-if="!isEditing" @click="startEdit" class="cursor-pointer hover:bg-gray-50 rounded px-1">
      <span>{{ displayValue }}</span>
      <PencilIcon class="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100" />
    </div>
    <div v-else class="flex gap-2">
      <ClientLookup
        v-model="editValue"
        @update:selected-client="handleClientSelected"
        placeholder="Search client..."
        class="min-w-48"
      />
      <Button @click="confirm" size="sm">✓</Button>
      <Button @click="cancel" variant="outline" size="sm">✕</Button>
    </div>
  </div>
</template>
```

### Phase 2: Integrate with Existing Autosave

#### Extend Current Autosave Instance

```typescript
// In JobView.vue - extend existing autosave from tabs
const headerAutosave = computed(() => {
  // Use the same autosave instance from active tab
  return activeTabComponent.value?.autosave
})

const handleNameUpdate = (newName: string) => {
  if (headerAutosave.value) {
    headerAutosave.value.queueChange('name', newName)
  }
}
```

### Phase 3: Update Header Template

**Before:**

```vue
<h1 class="text-lg font-bold text-gray-900 leading-tight">
  {{ jobData?.name || 'Loading...' }}
</h1>
<p class="text-xs text-gray-500">
  Job #{{ jobData?.job_number }} • {{ jobData?.client_name }}
</p>
```

**After:**

```vue
<div class="group">
  <InlineEditText
    :value="jobData?.name"
    @update:value="handleNameUpdate"
    placeholder="Job name"
    class="text-lg font-bold text-gray-900"
  />
</div>
<div class="flex items-center gap-2 text-xs text-gray-500">
  <span>Job #{{ jobData?.job_number }}</span>
  <span>•</span>
  <InlineEditClient
    :value="jobData?.client_name"
    :client-id="jobData?.client_id"
    @update:client="handleClientUpdate"
    class="group"
  />
</div>
```

## User Experience

### Visual Design

- **Default**: Subtle hover effects indicate editability
- **Edit Mode**: Clear visual distinction with input styling
- **Saving**: Consistent with existing tab save indicators
- **Mobile**: Touch-friendly targets, simplified interactions

### Keyboard Navigation

- **Tab**: Navigate between editable fields
- **Enter**: Confirm edit
- **Escape**: Cancel edit and revert

## Implementation Steps

### Step 1: Create Components (2-3 hours)

1. Create `InlineEditText.vue`
2. Create `InlineEditClient.vue`
3. Add basic styling and interactions
4. Test components in isolation

### Step 2: Integrate with JobView (2 hours)

1. Replace static elements with inline edit components
2. Connect to existing autosave system
3. Update mobile and desktop layouts
4. Test data synchronization

### Step 3: Polish and Test (1 hour)

1. Fine-tune hover effects and transitions
2. Test keyboard navigation
3. Verify mobile responsiveness
4. Test error handling

## Success Criteria

### Functional

- ✅ Job name editable inline with autosave
- ✅ Client selection with autosave and contact clearing
- ✅ Data synchronization with tabs
- ✅ Error handling and recovery

### Non-Functional

- ✅ Mobile-responsive design
- ✅ Keyboard navigation support
- ✅ Visual consistency with existing design
- ✅ No performance degradation

## Risk Mitigation

### Data Synchronization

- **Risk**: Header and tabs editing same data simultaneously
- **Mitigation**: Use shared autosave instance, coordinate updates

### Mobile UX

- **Risk**: Complex interactions on small screens
- **Mitigation**: Larger touch targets, simplified edit flows

### Performance

- **Risk**: Additional reactive watchers
- **Mitigation**: Efficient component design, minimal re-renders

## Dependencies

### Existing Components

- [`ClientLookup.vue`](src/components/ClientLookup.vue) ✅
- [`createJobAutosave`](src/composables/useJobAutosave.ts) ✅
- [`jobService.updateJob()`](src/services/job.service.ts) ✅

### New Components

- `InlineEditText.vue` - To be created
- `InlineEditClient.vue` - To be created

## Conclusion

This refactor will provide a seamless inline editing experience in the job header while leveraging the robust autosave system already implemented in the tabs. The phased approach ensures minimal risk and allows for iterative refinement.

The implementation focuses on the most commonly edited fields (job name and client) while maintaining the existing design language and user experience patterns.
