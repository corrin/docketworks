# SmartCostLinesTable Type Column Auto-Inference Implementation Plan

## Overview

Modify SmartCostLinesTable.vue to automatically infer the "Type" column (kind field) based on user actions, making it readonly while maintaining all existing functionality.

## Requirements

- **Item Selection**: When user selects an item → kind = 'material'
- **Labour Selection**: When user selects special "Labour" item → kind = 'time'
- **Description First**: When user types in description without selecting item → kind = 'adjust'
- **Type Column**: Becomes readonly (badge only, no dropdown)
- **Backward Compatibility**: Maintain existing validations and autosave logic

## Current State Analysis

### Type Column Behavior

- Currently uses dropdown menu for manual kind selection ('material', 'time', 'adjust')
- Editable based on `canEditKindForLine()` function
- Changes trigger company defaults application and unit_rev recalculation

### Item Selection

- Uses ItemSelect component with stock items from store
- Calls `onItemSelected(line)` when item changes

### Description Editing

- Editable via modal, currently doesn't affect kind

## Implementation Plan

### 1. Modify ItemSelect Component (`src/views/purchasing/ItemSelect.vue`)

#### Add Mocked "Labour" Item

```typescript
// Add after filteredItems computed
const mockedLabourItem = {
  id: '__labour__',
  description: 'Labour',
  item_code: 'LABOUR',
  unit_cost: companyDefaultsStore.companyDefaults?.wage_rate ?? 0,
  unit_rev: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
  quantity: null,
}

// Modify filteredItems to include mocked item
const filteredItems = computed(() => {
  const stockItems = store.items
  const labourItem = [mockedLabourItem]

  const allItems = [...stockItems, ...labourItem]

  if (!searchTerm.value) return allItems
  const term = searchTerm.value.toLowerCase()
  return allItems.filter((item) => {
    const searchableFields = [item.description, item.item_code].filter(Boolean)
    return searchableFields.some((field) => field?.toLowerCase().includes(term))
  })
})
```

#### Update Display Logic

```typescript
const displayLabel = computed(() => {
  if (!props.modelValue) return 'Select Item'
  if (props.modelValue === '__labour__') return 'Labour'
  const found = store.items.find((i: StockItem) => i.id == props.modelValue)
  return found ? found.description || 'Stock Item' : 'Select Item'
})
```

#### Add Kind Emit

```typescript
const emit = defineEmits<{
  'update:modelValue': [string | null]
  'update:description': [string]
  'update:unit_cost': [number | null]
  'update:kind': [KindOption | null] // New emit
}>()

// Update emit logic
'onUpdate:modelValue': (val) => {
  emit('update:modelValue', val as string | null)

  if (val === '__labour__') {
    emit('update:description', 'Labour')
    emit('update:unit_cost', companyDefaultsStore.companyDefaults?.wage_rate ?? 0)
    emit('update:kind', 'time')
  } else {
    const found = store.items.find((i: StockItem) => i.id == val)
    if (found) {
      emit('update:description', found.description || '')
      emit('update:unit_cost', found.unit_cost || null)
      emit('update:kind', 'material')
    } else {
      emit('update:description', '')
      emit('update:unit_cost', null)
      emit('update:kind', null)
    }
  }
}
```

### 2. Update SmartCostLinesTable.vue Type Column

#### Make Type Column Readonly

Replace the entire Type column cell (lines 344-459) with:

```typescript
// Type / Kind - Now readonly badge only
{
  id: 'kind',
  header: 'Type',
  cell: ({ row }: RowCtx) => {
    const line = displayLines.value[row.index]
    const badge = getKindBadge(line)
    return h(Badge, { class: `text-xs font-medium ${badge.class}` }, () => badge.label)
  },
  meta: { editable: false }, // Always readonly
},
```

### 3. Update Item Column Logic

#### Modify ItemSelect Usage

In the Item column cell, update the ItemSelect component to handle kind inference:

```typescript
h(ItemSelect, {
  modelValue: model,
  disabled: !enabled,
  onClick: (e: Event) => e.stopPropagation(),
  'onUpdate:modelValue': async (val: string | null) => {
    if (!enabled) return
    selectedItemMap.set(line, val)

    // Infer kind based on selection
    let newKind: KindOption = 'adjust' // Default fallback
    if (val === '__labour__') {
      newKind = 'time'
    } else if (val) {
      newKind = 'material'
    }

    // Update kind if it changed
    if (String(line.kind) !== newKind) {
      updateLineKind(line, newKind)
    }

    onItemSelected(line)

    // ... rest of existing logic for stock consumption and data updates
  },
  'onUpdate:description': (desc: string) => enabled && Object.assign(line, { desc }),
  'onUpdate:unit_cost': (cost: number | null) => {
    if (!enabled) return
    Object.assign(line, { unit_cost: Number(cost ?? 0) })
    if (kind !== 'time')
      Object.assign(line, { unit_rev: apply(line).derived.unit_rev })
    nextTick(() => {
      if (!line.id && isLineReadyForSave(line)) maybeEmitCreate(line)
    })
  },
}),
```

### 4. Add Description Change Handler

#### Infer 'adjust' Kind on Description Edit

Update the description modal save logic:

```typescript
// In the description modal
'update:modelValue': (desc: string) => {
  if (descModalLine) {
    descModalLine.desc = desc

    // Infer kind as 'adjust' if no item is selected and description is being set
    const hasSelectedItem = selectedItemMap.get(descModalLine)
    if (!hasSelectedItem && desc.trim() && String(descModalLine.kind) !== 'adjust') {
      updateLineKind(descModalLine, 'adjust')
    }
  }
}
```

### 5. Create Helper Function for Kind Updates

#### Add updateLineKind Helper

```typescript
function updateLineKind(line: CostLine, newKind: KindOption) {
  if (String(line.kind) === newKind) return

  Object.assign(line, { kind: newKind })
  onKindChanged(line)

  // Apply company defaults for time
  if (newKind === 'time') {
    Object.assign(line, {
      unit_cost: companyDefaultsStore.companyDefaults?.wage_rate ?? 0,
      unit_rev: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
    })
  } else {
    // Recalculate unit_rev with markup for material/adjust
    const derived = apply(line).derived
    Object.assign(line, { unit_rev: derived.unit_rev })
  }

  // Save if line has real ID and meets baseline
  if (line.id && isLineReadyForSave(line)) {
    console.log('Saving kind change:', line.id, newKind)
    const patch: PatchedCostLineCreateUpdate = {
      kind: newKind,
      ...(newKind === 'time'
        ? {
            unit_cost: companyDefaultsStore.companyDefaults?.wage_rate ?? 0,
            unit_rev: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
          }
        : { unit_rev: Number(line.unit_rev) }),
    }
    const optimistic: Partial<CostLine> = { ...patch }
    autosave.scheduleSave(line, patch, optimistic)
  }
}
```

### 6. Update Props Interface

#### Remove allowTypeEdit Prop

```typescript
const props = withDefaults(
  defineProps<{
    // ... other props
    // Remove allowTypeEdit?: boolean
    // ... rest
  }>(),
  {
    // ... defaults
    // Remove allowTypeEdit: true,
  },
)
```

### 7. Remove Old Logic

#### Clean Up

- Remove `canEditKindForLine()` function
- Remove all dropdown menu logic in Type column
- Remove `allowTypeEdit` prop handling

## Testing Strategy

### Test Cases

1. **Item Selection:**

   - Select regular stock item → kind = 'material'
   - Select "Labour" item → kind = 'time'
   - Verify unit_cost/unit_rev update correctly

2. **Description Typing:**

   - Type in description without item → kind = 'adjust'
   - Verify kind changes appropriately

3. **Autosave:**

   - Changes to existing lines should autosave
   - New lines should emit create when ready

4. **Validations:**
   - Ensure existing validations still work
   - Kind changes don't break calculations

## Files to Modify

1. `src/views/purchasing/ItemSelect.vue` - Add mocked Labour item and kind emit
2. `src/components/shared/SmartCostLinesTable.vue` - Main implementation

## Backward Compatibility

- All existing functionality preserved
- Autosave and validation logic unchanged
- Props interface updated (allowTypeEdit removed)
- Type column becomes readonly but still displays correct information

## Risk Assessment

- **Low Risk**: Changes are additive and maintain existing behavior
- **Testing Required**: Need to verify kind inference works in all scenarios
- **Data Integrity**: Existing cost line data remains unchanged
