# Code Examples and Focused Snippets — Inline Delivery Receipt (Current Model, no i18n)

These snippets are implementation‑oriented and aligned with the current flow and schemas:

- POST a DeliveryReceiptRequest for a single line at a time
- Refresh Purchase Order and Existing Allocations after save
- No lots/serials, no bins/locations hierarchy, no UoM conversions, no drafts/commit lifecycle

Authoritative references:

- [`DeliveryReceiptFormView.vue`](src/views/purchasing/DeliveryReceiptFormView.vue:1)
- [`DeliveryReceiptLinesTable.vue`](src/components/purchasing/DeliveryReceiptLinesTable.vue:1)
- [`deliveryReceiptStore.ts`](src/stores/deliveryReceiptStore.ts:1)
- [`delivery-receipt.ts`](src/utils/delivery-receipt.ts:1)
- [`api.ts`](src/api/generated/api.ts:1555)

---

## 1) Add “Receipt” column in PoLinesTable.vue

Add a new column that mounts the inline editor for each line. The table remains presentational (no direct API calls).

Imports (near other imports) in [`PoLinesTable.vue`](src/components/purchasing/PoLinesTable.vue:1):

```ts
import AllocationCellEditor from '@/components/purchasing/AllocationCellEditor.vue'
```

Extend props and emits in [`PoLinesTable.vue`](src/components/purchasing/PoLinesTable.vue:24):

```ts
type Props = {
  // existing props...
  lines: PurchaseOrderLine[]
  jobs: JobForPurchasing[]
  // new props
  existingAllocations?: Record<string, AllocationItem[]>
  defaultRetailRate?: number
  stockHoldingJobId?: string
}

type Emits = {
  // existing emits...
  (e: 'receipt:save', payload: { lineId: string; editorState: LineEditorState }): void
}

interface LineEditorState {
  rows: {
    target: 'job' | 'stock'
    job_id?: string
    quantity: number
    retail_rate?: number // UI-only today
    stock_location?: string // UI-only today
  }[]
}
```

Add the column definition before “actions” in [`PoLinesTable.vue`](src/components/purchasing/PoLinesTable.vue:108):

```ts
{
  id: 'receipt',
  header: 'Receipt',
  cell: ({ row }: DataTableRowContext) => {
    const line = row.original
    const lineId = line.id as string
    const existing = props.existingAllocations?.[lineId] || []
    return h(AllocationCellEditor, {
      line,
      jobs: props.jobs,
      existing,
      defaultRetailRate: props.defaultRetailRate,
      stockHoldingJobId: props.stockHoldingJobId,
      disabled: props.readOnly,
      onSave: (editorState: any) => emit('receipt:save', { lineId, editorState }),
    })
  },
  meta: { editable: !props.readOnly },
},
```

Notes:

- Remaining is computed inside AllocationCellEditor (using line + existing).
- Emitting “receipt:save” bubbles to the parent view, which will call the store.

---

## 2) New AllocationCellEditor.vue

Create a simple inline popover editor. It owns only UI state and emits autosave payloads on blur/close with debounce.

[`src/components/purchasing/AllocationCellEditor.vue`](src/components/purchasing/AllocationCellEditor.vue:1):

```vue
<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'

type PurchaseOrderLine = z.infer<typeof schemas.PurchaseOrderLine>
type JobForPurchasing = z.infer<typeof schemas.JobForPurchasing>
type AllocationItem = z.infer<typeof schemas.AllocationItem>

interface Props {
  line: PurchaseOrderLine
  jobs: JobForPurchasing[]
  existing: AllocationItem[]
  defaultRetailRate?: number
  stockHoldingJobId?: string
  disabled?: boolean
}
const props = defineProps<Props>()

const emit = defineEmits<{
  save: [editorState: { rows: EditorRow[] }]
  close: []
}>()

interface EditorRow {
  target: 'job' | 'stock'
  job_id?: string
  quantity: number
  retail_rate?: number // UI-only (not posted today)
  stock_location?: string // UI-only (not posted today)
}

const open = ref(false)
const rows = ref<EditorRow[]>([])

// Derived “this receipt” total and remaining (based on saved allocations only)
const thisReceiptTotal = computed(() =>
  rows.value.reduce((s, r) => s + (Number(r.quantity) || 0), 0),
)
const savedTotalForLine = computed(() => props.existing.reduce((s, a) => s + (a.quantity || 0), 0))
const remaining = computed(() => {
  const baseRemaining = Math.max(
    0,
    (props.line.quantity || 0) - (props.line.received_quantity || 0),
  )
  return Math.max(0, baseRemaining - savedTotalForLine.value)
})

// Inline validation
const overReceipt = computed(() => thisReceiptTotal.value > remaining.value)
const hasNegative = computed(() => rows.value.some((r) => (r.quantity ?? 0) < 0))

function openEditor() {
  if (props.disabled) return
  if (!rows.value.length) {
    // default row
    const firstNonStock = props.jobs.find((j) => !j.is_stock_holding)
    rows.value.push({
      target: firstNonStock ? 'job' : 'stock',
      job_id: firstNonStock ? firstNonStock.id : props.stockHoldingJobId,
      quantity: Math.min(1, remaining.value),
      retail_rate: firstNonStock ? (props.defaultRetailRate ?? 0) : undefined,
    })
  }
  open.value = true
  nextTick(() => {
    // focus if needed
  })
}

function closeEditor() {
  open.value = false
  emit('close')
}

// Quick actions
function allocateRemaining() {
  if (!remaining.value) return
  if (!rows.value.length) {
    rows.value.push({
      target: 'stock',
      job_id: props.stockHoldingJobId,
      quantity: remaining.value,
    })
  } else {
    rows.value[0].quantity = remaining.value
  }
}

function allocateAll() {
  allocateRemaining()
}

// Autosave on blur/close with debounce
let debounceTimer: any = null
function scheduleSave() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => doSave(), 200)
}

function doSave() {
  // Clean zero rows
  rows.value = rows.value.filter((r) => Number(r.quantity) > 0)

  if (!rows.value.length) return
  if (hasNegative.value || overReceipt.value) return

  emit('save', { rows: rows.value })
}

// Watch rows to autosave
watch(rows, scheduleSave, { deep: true })
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <Button
        size="sm"
        variant="outline"
        :disabled="disabled"
        :aria-label="`Edit receipt allocations for line ${line.id}`"
        @click.stop.prevent="openEditor"
      >
        This Receipt: {{ thisReceiptTotal }} • Remaining: {{ remaining }}
      </Button>
    </PopoverTrigger>
    <PopoverContent
      class="w-[560px]"
      role="dialog"
      :aria-label="`Receipt editor for line ${line.id}`"
    >
      <div class="flex items-center justify-between mb-2">
        <div class="text-sm font-medium">Receipt</div>
        <div class="flex gap-2">
          <Button size="xs" variant="ghost" :disabled="!remaining" @click="allocateRemaining"
            >Allocate remaining</Button
          >
          <Button size="xs" variant="ghost" :disabled="!remaining" @click="allocateAll"
            >Allocate all</Button
          >
        </div>
      </div>

      <div
        v-if="overReceipt"
        class="p-2 mb-2 text-xs rounded border border-red-200 bg-red-50 text-red-700"
      >
        Exceeds remaining
      </div>

      <div class="max-h-64 overflow-auto pr-1 space-y-2">
        <div v-for="(r, idx) in rows" :key="idx" class="grid grid-cols-6 gap-2 items-center">
          <select
            class="col-span-2 border rounded px-2 py-1 text-sm"
            v-model="r.target"
            @change="
              () => {
                if (r.target === 'stock') {
                  r.job_id = props.stockHoldingJobId
                  r.retail_rate = undefined
                } else {
                  const firstNonStock = props.jobs.find((j) => !j.is_stock_holding)
                  r.job_id = firstNonStock?.id || undefined
                  r.retail_rate = r.retail_rate ?? props.defaultRetailRate ?? 0
                }
              }
            "
          >
            <option value="stock">Stock</option>
            <option value="job">Job</option>
          </select>

          <select
            v-if="r.target === 'job'"
            class="col-span-2 border rounded px-2 py-1 text-sm"
            v-model="r.job_id"
          >
            <option
              v-for="j in props.jobs.filter((j) => !j.is_stock_holding)"
              :key="j.id"
              :value="j.id"
            >
              {{ j.name }}
            </option>
          </select>

          <Input
            type="number"
            class="col-span-1 text-right"
            v-model.number="r.quantity"
            aria-label="Quantity"
            :min="0"
          />

          <div class="col-span-1 flex items-center justify-end gap-2">
            <Button size="xs" variant="outline" @click="rows.splice(idx, 1)">×</Button>
          </div>

          <!-- Retail rate (UI-only) -->
          <div v-if="r.target === 'job'" class="col-span-6 -mt-1">
            <label class="text-xs text-gray-600"
              >Retail rate (%) — Not applied to saved receipt yet</label
            >
            <Input
              type="number"
              class="w-full"
              v-model.number="r.retail_rate"
              min="0"
              max="100"
              step="0.01"
            />
          </div>

          <!-- Stock location (UI-only) -->
          <div v-if="r.target === 'stock'" class="col-span-6 -mt-1">
            <label class="text-xs text-gray-600"
              >Stock location — Note only; not saved to server</label
            >
            <Input class="w-full" v-model="r.stock_location" />
          </div>
        </div>
      </div>

      <div class="flex justify-between mt-3">
        <Button
          size="sm"
          variant="outline"
          @click="
            rows.push({
              target: 'stock',
              job_id: props.stockHoldingJobId,
              quantity: Math.min(1, remaining),
            })
          "
          >+ Add</Button
        >
        <div class="text-xs text-gray-500">This Receipt: {{ thisReceiptTotal }}</div>
      </div>
    </PopoverContent>
  </Popover>
</template>
```

Key points:

- Autosave: watch rows with debounce; emit save with only UI state
- Validation inline: negative and over‑receipt block
- No persistence of retail_rate or stock_location (UI‑only hints)

---

## 3) Orchestrate in PurchaseOrderFormView.vue

In the PO form view, fetch jobs and existing allocations, pass to PoLinesTable, and handle “receipt:save” by posting a single‑line request via the existing store, then refresh.

Script additions in [`PurchaseOrderFormView.vue`](src/views/purchasing/PurchaseOrderFormView.vue:127):

```ts
import { useDeliveryReceiptStore } from '@/stores/deliveryReceiptStore'
import { transformDeliveryReceiptForAPI } from '@/utils/delivery-receipt'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

const receiptStore = useDeliveryReceiptStore()
const existingAllocations = ref<Record<string, z.infer<typeof schemas.AllocationItem>[]>>({})
const stockHoldingJobId = ref<string | null>(null)
const defaultRetailRate = computed(() => receiptStore.getDefaultRetailRate())

async function loadExistingAllocations() {
  const response = await receiptStore
    .fetchExistingAllocations(orderId)
    .catch(() => ({ allocations: {} }))
  existingAllocations.value = response.allocations || {}
}

async function loadJobsForReceipt() {
  const { stockHolding } = await receiptStore.fetchJobs()
  stockHoldingJobId.value = stockHolding?.id || null
}

type DeliveryAllocation = z.infer<typeof schemas.DeliveryReceiptAllocation>

const handleReceiptSave = async (payload: { lineId: string; editorState: { rows: any[] } }) => {
  if (!po.value) return
  const lineId = payload.lineId
  const rows = payload.editorState.rows

  // Map editor rows to API allocations: job_id + quantity only
  const apiAllocations: DeliveryAllocation[] = rows.map((r) => {
    const isStock = r.target === 'stock'
    return {
      job_id: isStock ? (stockHoldingJobId.value as string) : (r.job_id as string),
      quantity: Number(r.quantity) || 0,
    }
  })

  // Build single-line map using helper
  const map: Record<string, DeliveryAllocation[]> = { [lineId]: apiAllocations }
  const request = transformDeliveryReceiptForAPI(po.value.id, map)

  try {
    await receiptStore.submitDeliveryReceipt(po.value.id, request.allocations)
    toast.success('Receipt saved')
    await Promise.all([load(), loadExistingAllocations()])
  } catch (err) {
    toast.error('Failed to save receipt')
  }
}
```

Pass props and event to the table in template [`PurchaseOrderFormView.vue`](src/views/purchasing/PurchaseOrderFormView.vue:49):

```vue
<PoLinesTable
  :lines="po.lines"
  :items="xeroItemStore.items"
  :jobs="jobs"
  :read-only="!canEditLineItems"
  :jobs-read-only="!canEditJobs"
  :existing-allocations="existingAllocations"
  :default-retail-rate="defaultRetailRate"
  :stock-holding-job-id="stockHoldingJobId || undefined"
  @receipt:save="handleReceiptSave"
  @update:lines="canEditLineItems || canEditJobs ? (po.lines = $event) : null"
  @add-line="handleAddLineEvent"
  @delete-line="deleteLine"
/>
```

Extend onMounted sequence in [`PurchaseOrderFormView.vue`](src/views/purchasing/PurchaseOrderFormView.vue:773):

```ts
await Promise.all([
  xeroItemStore.fetchItems(),
  fetchJobs(),
  load(),
  loadJobsForReceipt(),
  loadExistingAllocations(),
])
```

---

## 4) Single‑line Request Build Using Existing Helper

The helper already builds a DeliveryReceiptRequest from `{ [lineId]: DeliveryReceiptLine }`. We simply pass a map with one entry to post just the edited line.

[`delivery-receipt.ts`](src/utils/delivery-receipt.ts:22) usage example:

```ts
const map: Record<string, DeliveryAllocation[]> = { [lineId]: apiAllocations }
const request = transformDeliveryReceiptForAPI(poId, map)
// request.allocations has the correct shape for submitDeliveryReceipt
await receiptStore.submitDeliveryReceipt(poId, request.allocations)
```

Note:

- retail_rate and stock_location remain UI‑only, not included in request until schema is extended.

---

## 5) Strings (for UI messages)

Use these messages directly (no i18n layer at this stage):

- Receipt
- This Receipt
- Remaining
- Allocate remaining
- Allocate all
- Exceeds remaining
- Quantity must be greater than or equal to 0
- Receipt saved
- Retail rate (%): Not applied to saved receipt yet
- Stock location: Note only; not saved to server

---

## 6) Summary

- Small, focused component + a single new table column
- Autosave posts one line at a time (partial map), then refresh
- No new store or endpoints; retail_rate and stock_location remain UI‑only for now
