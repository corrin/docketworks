<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import DataTable from '@/components/DataTable.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogDescription from '@/components/ui/dialog/DialogDescription.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import { Trash2, Settings2 } from 'lucide-vue-next'
import { metalTypeOptions } from '@/utils/metalType'
import ItemSelect from '@/views/purchasing/ItemSelect.vue'
import JobSelect from './JobSelect.vue'
import AllocationCellEditor from '@/components/purchasing/AllocationCellEditor.vue'
import { schemas } from '@/api/generated/api'
import type { DataTableRowContext } from '@/utils/data-table-types'
import type { ColumnDef } from '@tanstack/vue-table'
import { z } from 'zod'
import { debugLog } from '../../utils/debug'
import { useStockStore } from '@/stores/stockStore'
import type { StockItem } from '@/stores/stockStore'

type PurchaseOrderLine = z.infer<typeof schemas.PurchaseOrderLine>
type JobForPurchasing = z.infer<typeof schemas.JobForPurchasing>
type AllocationItem = z.infer<typeof schemas.AllocationItem>
type Props = {
  lines: PurchaseOrderLine[]
  jobs: JobForPurchasing[]
  readOnly?: boolean
  jobsReadOnly?: boolean
  // New props for receipt functionality
  existingAllocations?: Record<string, AllocationItem[]>
  defaultRetailRate?: number
  stockHoldingJobId?: string
  poStatus?: string
  poId: string
}

type Emits = {
  (e: 'update:lines', lines: PurchaseOrderLine[]): void
  (e: 'add-line'): void
  (e: 'delete-line', id: string | number): void
  (e: 'receipt:save', payload: { lineId: string; editorState: LineEditorState }): void
  (e: 'allocation-deleted', data: { allocationId: string; allocationType: string }): void
}

type AllocationEditorRow = {
  job_id: string
  quantity: number
  retail_rate?: number
  stock_location?: string
  metal_type?: string
  alloy?: string
  specifics?: string
  dimensions?: string
}

interface LineEditorState {
  rows: {
    target: 'job' | 'stock'
    job_id?: string
    quantity: number
    retail_rate?: number
    stock_location?: string
    metal_type?: string
    alloy?: string
    specifics?: string
    dimensions?: string
  }[]
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const stockStore = useStockStore()
type RowContext = DataTableRowContext<PurchaseOrderLine>

const showAdditionalFieldsModal = ref(false)
const editingLineIndex = ref<number>(-1)
const editingItemIndex = ref<number>(-1)
const additionalFields = ref({
  metal_type: '',
  alloy: '',
  specifics: '',
  location: '',
  dimensions: '',
})

const openAdditionalFieldsModal = (lineIndex: number) => {
  if (props.readOnly) return

  editingLineIndex.value = lineIndex
  const line = props.lines[lineIndex]

  additionalFields.value = {
    metal_type: String(line.metal_type || ''),
    alloy: String(line.alloy || ''),
    specifics: String(line.specifics || ''),
    location: String(line.location || ''),
    dimensions: String(line.dimensions || ''),
  }

  showAdditionalFieldsModal.value = true
}

const saveAdditionalFields = () => {
  if (editingLineIndex.value === -1) return

  const updated = props.lines.map((line, idx) =>
    idx === editingLineIndex.value
      ? {
          ...line,
          metal_type: additionalFields.value.metal_type || undefined,
          alloy: additionalFields.value.alloy || undefined,
          specifics: additionalFields.value.specifics || undefined,
          location: additionalFields.value.location || undefined,
          dimensions: additionalFields.value.dimensions || undefined,
        }
      : line,
  )

  emit('update:lines', updated)
  closeAdditionalFieldsModal()
}

const closeAdditionalFieldsModal = () => {
  showAdditionalFieldsModal.value = false
  editingLineIndex.value = -1
  additionalFields.value = {
    metal_type: '',
    alloy: '',
    specifics: '',
    location: '',
    dimensions: '',
  }
}

const updateLine = (index: number, updates: Partial<PurchaseOrderLine>) => {
  const updated = props.lines.map((line, idx) => (idx === index ? { ...line, ...updates } : line))
  emit('update:lines', updated)
}

const handleAddLine = () => {
  if (props.readOnly) {
    return
  }

  emit('add-line')
}

const isPoSubmitted = computed(() => props.poStatus === 'submitted_to_supplier')
const isColumnDisabled = computed(() => props.readOnly || isPoSubmitted.value)

// Check if Receipt column should be visible based on PO status
const isReceiptColumnVisible = computed(() => {
  const validStatuses = [
    'submitted',
    'submitted_to_supplier',
    'partially_received',
    'fully_received',
  ]
  return validStatuses.includes(props.poStatus || '')
})

const columns = computed<ColumnDef<PurchaseOrderLine>[]>(() => {
  const columnDefs: ColumnDef<PurchaseOrderLine>[] = [
    {
      id: 'item_code',
      header: 'Item',
      cell: (context: RowContext) => {
        const isEditing = editingItemIndex.value === context.row.index

        if (isEditing) {
          // Show ItemSelect when editing
          return h(ItemSelect, {
            modelValue: context.row.original.item_code ?? null,
            disabled: isColumnDisabled.value,
            showQuantity: false,
            'onUpdate:modelValue': isColumnDisabled.value
              ? undefined
              : (val: string | null) => {
                  debugLog('PoLinesTable: Received modelValue update:', val)
                  debugLog('PoLinesTable: Available stock items:', stockStore.items.length)

                  const found = stockStore.items.find((i: StockItem) => i.id === val)
                  debugLog('PoLinesTable: Found stock item:', found)

                  updateLine(context.row.index, {
                    // Auto-populate all fields from stock item when selected
                    ...(found && {
                      description: found.description,
                      unit_cost: found.unit_cost,
                      metal_type: found.metal_type,
                      alloy: found.alloy,
                      specifics: found.specifics,
                      location: found.location,
                      item_code: found.item_code || null,
                    }),
                  })

                  // Exit edit mode after selection
                  editingItemIndex.value = -1
                },
          })
        } else {
          // Show item code button when not editing
          const itemCode = context.row.original.item_code
          const displayText = itemCode || 'Select Item'

          return h('div', { class: 'col-item flex items-center' }, [
            h(
              Button,
              {
                variant: 'outline',
                size: 'sm',
                disabled: isColumnDisabled.value,
                onClick: isColumnDisabled.value
                  ? undefined
                  : (e: Event) => {
                      e.stopPropagation()
                      editingItemIndex.value = context.row.index
                    },
                class: 'font-mono uppercase tracking-wide',
              },
              () => displayText,
            ),
          ])
        }
      },
      meta: { editable: !isColumnDisabled.value },
    },
    {
      id: 'description',
      header: 'Description',
      cell: (context: RowContext) =>
        h(Input, {
          modelValue: context.row.original.description,
          disabled: isColumnDisabled.value,
          class: 'w-full',
          'data-automation-id': `PoLinesTable-description-${context.row.index}`,
          onClick: (e: Event) => e.stopPropagation(),
          'onUpdate:modelValue': isColumnDisabled.value
            ? undefined
            : (val: string | number) => {
                if (typeof val === 'string') {
                  updateLine(context.row.index, { description: val })
                }
              },
        }),
    },
    {
      id: 'job_id',
      header: 'Job',
      cell: (context: RowContext) =>
        h(JobSelect, {
          modelValue: context.row.original.job_id || '',
          required: false,
          placeholder: 'Select Job (Optional)',
          jobs: props.jobs,
          disabled: props.jobsReadOnly ?? isColumnDisabled.value,
          'onUpdate:modelValue':
            (props.jobsReadOnly ?? isColumnDisabled.value)
              ? undefined
              : (val: string | null) => {
                  updateLine(context.row.index, { job_id: val || undefined })
                },
          onJobSelected:
            (props.jobsReadOnly ?? isColumnDisabled.value)
              ? undefined
              : (job: JobForPurchasing | null) => {
                  if (job) {
                    updateLine(context.row.index, {
                      job_id: job.id,
                      job_number: job.job_number,
                      job_name: job.name,
                      client_name: job.client_name,
                    })
                  }
                },
        }),
      meta: { editable: !(props.jobsReadOnly ?? isColumnDisabled.value) },
    },
    {
      id: 'quantity',
      header: 'Qty',
      cell: (context: RowContext) =>
        h(Input, {
          type: 'number',
          step: '1',
          min: '0',
          modelValue: context.row.original.quantity,
          disabled: isColumnDisabled.value,
          class: 'w-20 text-right',
          'data-automation-id': `PoLinesTable-quantity-${context.row.index}`,
          onClick: (e: Event) => e.stopPropagation(),
          'onUpdate:modelValue': isColumnDisabled.value
            ? undefined
            : (val: string | number) => {
                const num = Number(val)
                if (!Number.isNaN(num)) {
                  updateLine(context.row.index, { quantity: num })
                }
              },
        }),
    },
    {
      id: 'unit_cost',
      header: 'Unit Cost',
      cell: (context: RowContext) =>
        h(Input, {
          type: 'number',
          step: '0.01',
          min: '0',
          modelValue: context.row.original.unit_cost ?? '',
          disabled: context.row.original.price_tbc || isColumnDisabled.value,
          class: 'w-24 text-right',
          'data-automation-id': `PoLinesTable-unit-cost-${context.row.index}`,
          onClick: (e: Event) => e.stopPropagation(),
          'onUpdate:modelValue': isColumnDisabled.value
            ? undefined
            : (val: string | number) => {
                const cost = val === '' ? null : Number(val)
                updateLine(context.row.index, { unit_cost: cost })
              },
        }),
    },
    {
      id: 'price_tbc',
      header: 'Price TBC',
      cell: (context: RowContext) =>
        h(Checkbox, {
          modelValue: context.row.original.price_tbc,
          disabled:
            (context.row.original.unit_cost !== null &&
              Number(context.row.original.unit_cost) > 0) ||
            isColumnDisabled.value,
          'onUpdate:modelValue': isColumnDisabled.value
            ? undefined
            : (checked: boolean | 'indeterminate') => {
                if (typeof checked === 'boolean') {
                  updateLine(context.row.index, { price_tbc: checked })
                }
              },
          class: 'mx-auto',
        }),
      meta: { editable: !isColumnDisabled.value },
    },
    {
      id: 'additional_fields',
      header: 'Additional Fields',
      cell: (context: RowContext) => {
        const hasAdditionalData = !!(
          context.row.original.metal_type ||
          context.row.original.alloy ||
          context.row.original.specifics ||
          context.row.original.location ||
          context.row.original.dimensions
        )

        return h(
          Button,
          {
            variant: hasAdditionalData ? 'default' : 'outline',
            size: 'sm',
            disabled: isColumnDisabled.value,
            onClick: isColumnDisabled.value
              ? undefined
              : () => openAdditionalFieldsModal(context.row.index),
          },
          () => [h(Settings2, { class: 'w-4 h-4 mr-1' }), hasAdditionalData ? 'Edit' : 'Add'],
        )
      },
      meta: { editable: !isColumnDisabled.value },
    },
    {
      id: 'receipt',
      header: 'Receipt',
      cell: (context: RowContext) => {
        const line = context.row.original
        const lineId = line.id as string

        // Only show receipt editor for lines that have been saved (have an ID)
        if (!lineId) {
          return h('div', { class: 'text-xs text-gray-500 text-center p-2' }, 'Save line first')
        }

        const existing = props.existingAllocations?.[lineId] || []
        return h(AllocationCellEditor, {
          line,
          jobs: props.jobs,
          existing,
          defaultRetailRate: props.defaultRetailRate,
          stockHoldingJobId: props.stockHoldingJobId,
          poStatus: props.poStatus,
          poId: props.poId,
          onSave: (editorState: { rows: AllocationEditorRow[] }) => {
            const normalized: LineEditorState = {
              rows: editorState.rows.map((row) => ({
                ...row,
                target: row.job_id === props.stockHoldingJobId ? 'stock' : 'job',
              })),
            }
            emit('receipt:save', { lineId, editorState: normalized })
          },
          onAllocationDeleted: (data: { allocationId: string; allocationType: string }) =>
            emit('allocation-deleted', data),
        })
      },
      meta: { editable: !props.readOnly },
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: (context: RowContext) =>
        h(
          Button,
          {
            variant: 'destructive',
            size: 'icon',
            disabled: isColumnDisabled.value,
            onClick: isColumnDisabled.value
              ? undefined
              : () => {
                  if (context.row.original.id) {
                    emit('delete-line', context.row.original.id)
                  } else {
                    emit('delete-line', context.row.index)
                  }
                },
          },
          () => h(Trash2, { class: 'w-4 h-4' }),
        ),
      meta: { editable: !isColumnDisabled.value },
    },
  ]
  return columnDefs.filter((column) => {
    // Hide Receipt column when PO status doesn't allow receipts
    if (column.id === 'receipt' && !isReceiptColumnVisible.value) {
      return false
    }
    return true
  })
})

onMounted(() => {
  debugLog('Props ', props)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <div class="flex-1 overflow-y-auto max-h-[60vh]">
      <DataTable
        :columns="columns"
        :data="props.lines"
        @rowClick="() => {}"
        :page-size="1000"
        :hide-footer="true"
      />
    </div>
    <div class="sticky bottom-0 bg-white z-10 p-2 border-t">
      <Button
        class="w-full"
        :disabled="isColumnDisabled"
        @click="handleAddLine"
        data-automation-id="PoLinesTable-add-line"
      >
        ＋ Add line
      </Button>
    </div>

    <!-- Additional Fields Modal using Dialog component -->
    <Dialog v-model:open="showAdditionalFieldsModal">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>Additional Fields</DialogTitle>
          <DialogDescription>
            Fill in additional details for this purchase order line.
          </DialogDescription>
        </DialogHeader>

        <div class="space-y-4 py-4">
          <!-- Metal Type -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1"> Metal Type </label>
            <select
              v-model="additionalFields.metal_type"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">Select metal type...</option>
              <option v-for="option in metalTypeOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>

          <!-- Alloy -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1"> Alloy </label>
            <Input v-model="additionalFields.alloy" type="text" placeholder="e.g., 304, 6061" />
          </div>

          <!-- Specifics -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1"> Specifics </label>
            <Input
              v-model="additionalFields.specifics"
              type="text"
              placeholder="e.g., m8 countersunk socket screw"
            />
          </div>

          <!-- Location -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1"> Location </label>
            <Input
              v-model="additionalFields.location"
              type="text"
              placeholder="Where this item will be stored"
            />
          </div>

          <!-- Dimensions -->
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1"> Dimensions </label>
            <Input
              v-model="additionalFields.dimensions"
              type="text"
              placeholder="Product dimensions"
            />
          </div>
        </div>

        <div class="flex justify-end space-x-3">
          <Button variant="outline" @click="closeAdditionalFieldsModal"> Cancel </Button>
          <Button @click="saveAdditionalFields"> Save </Button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
