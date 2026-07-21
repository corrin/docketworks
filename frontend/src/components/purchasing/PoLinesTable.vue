<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import DataTable from '@/components/DataTable.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Trash2 } from 'lucide-vue-next'
import ItemSelect from '@/views/purchasing/ItemSelect.vue'
import JobSelect from './JobSelect.vue'
import AllocationCellEditor from '@/components/purchasing/AllocationCellEditor.vue'
import { schemas } from '@/api/generated/api'
import type { DataTableRowContext } from '@/utils/data-table-types'
import type { ColumnDef } from '@tanstack/vue-table'
import { z } from 'zod'
import { debugLog } from '../../utils/debug'
import {
  gridCellAttrs,
  handleGridCellKeydown,
  useGridKeyboardNav,
} from '@/composables/useGridKeyboardNav'
import { usePhantomRow } from '@/composables/usePhantomRow'

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

function isSelectableStockItem(value: unknown): value is {
  description: string
  unit_cost: number
  metal_type?: string
  alloy?: string | null
  specifics?: string | null
  location?: string
  item_code?: string | null
  times_used?: number
  id: string
} {
  if (!value || typeof value !== 'object') return false
  if (!('id' in value)) return false
  // Labour picker items (type: 'labour') are never stock; PO lines don't see
  // them today (no tabKind passed), but stay strict about the payload shape.
  if ((value as { type?: unknown }).type === 'labour') return false
  return 'description' in value && 'unit_cost' in value
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

type RowContext = DataTableRowContext<PurchaseOrderLine>

const openItemSelectIndex = ref<number>(-1)
const containerRef = ref<HTMLElement | null>(null)
const selectedRowIndex = ref<number>(-1)

function makeEmptyLine(): PurchaseOrderLine {
  return {
    id: '',
    description: '',
    quantity: 1,
    dimensions: undefined,
    unit_cost: 0,
    price_tbc: false,
    supplier_item_code: undefined,
    item_code: '',
    received_quantity: undefined,
    metal_type: undefined,
    alloy: undefined,
    specifics: undefined,
    location: undefined,
    job_id: null,
    job_number: null,
    company_name: null,
    job_name: null,
    times_used: 0,
  }
}

const {
  displayRows: displayLines,
  isPhantomIndex,
  promotePhantom,
  selectPhantom,
} = usePhantomRow<PurchaseOrderLine & { __localId?: string }>({
  rows: () => props.lines,
  makePhantom: makeEmptyLine,
})

const updateLine = (index: number, updates: Partial<PurchaseOrderLine>) => {
  if (index < props.lines.length) {
    const updated = props.lines.map((line, idx) => (idx === index ? { ...line, ...updates } : line))
    emit('update:lines', updated)
    return
  }

  emit('update:lines', [...props.lines, promotePhantom(updates)])
}

const handleAddLine = () => {
  if (props.readOnly) {
    return
  }

  selectPhantom((index) => (selectedRowIndex.value = index))
}

const isPoSubmitted = computed(() => props.poStatus === 'submitted_to_supplier')
const isColumnDisabled = computed(() => props.readOnly || isPoSubmitted.value)

const { onKeydown } = useGridKeyboardNav({
  getRowCount: () => displayLines.value.length,
  getSelectedIndex: () => selectedRowIndex.value,
  setSelectedIndex: (index) => (selectedRowIndex.value = index),
  addLine: handleAddLine,
  deleteSelected: () => {
    const index = selectedRowIndex.value
    if (index < 0 || index >= props.lines.length || isColumnDisabled.value) return
    const line = props.lines[index]
    emit('delete-line', line.id || index)
  },
})

function handleCellNav(e: KeyboardEvent, rowIndex: number, columnId: string): boolean {
  return handleGridCellKeydown(e, {
    container: containerRef.value,
    rowIndex,
    columnId,
  })
}

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
        const itemCode = context.row.original.item_code
        const displayText = itemCode || 'Select Item'
        const isOpen = openItemSelectIndex.value === context.row.index

        if (!isOpen) {
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
                      openItemSelectIndex.value = context.row.index
                    },
                class: 'font-mono uppercase tracking-wide',
              },
              () => displayText,
            ),
          ])
        }

        return h(ItemSelect, {
          modelValue: null,
          open: isOpen,
          disabled: isColumnDisabled.value,
          showQuantity: false,
          lineKind: 'material',
          'onUpdate:open': (val: boolean) => {
            openItemSelectIndex.value = val ? context.row.index : -1
          },
          'onUpdate:modelValue': isColumnDisabled.value
            ? undefined
            : () => {
                // Selection side-effects are driven from `selectedItem` so the
                // PO table does not need a separate lookup path.
              },
          onSelectedItem: isColumnDisabled.value
            ? undefined
            : (selected) => {
                debugLog('PoLinesTable: Received selected item:', selected)
                if (!isSelectableStockItem(selected)) {
                  openItemSelectIndex.value = -1
                  return
                }

                updateLine(context.row.index, {
                  ...(selected && {
                    description: selected.description,
                    unit_cost: selected.unit_cost,
                    metal_type: selected.metal_type,
                    alloy: selected.alloy,
                    specifics: selected.specifics,
                    location: selected.location,
                    item_code: selected.item_code || null,
                    times_used: selected.times_used ?? 0,
                  }),
                })

                openItemSelectIndex.value = -1
              },
        })
      },
      meta: { editable: !isColumnDisabled.value },
    },
    {
      id: 'times_used',
      header: 'Times Used',
      cell: (context: RowContext) =>
        h(
          'div',
          { class: 'text-center tabular-nums text-sm text-gray-700' },
          String(context.row.original.times_used ?? 0),
        ),
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
          ...gridCellAttrs(context.row.index, 'description'),
          onClick: (e: Event) => e.stopPropagation(),
          onKeydown: (e: KeyboardEvent) => handleCellNav(e, context.row.index, 'description'),
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
                      company_name: job.company_name,
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
          ...gridCellAttrs(context.row.index, 'quantity'),
          onClick: (e: Event) => e.stopPropagation(),
          onKeydown: (e: KeyboardEvent) => handleCellNav(e, context.row.index, 'quantity'),
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
          ...gridCellAttrs(context.row.index, 'unit_cost'),
          onClick: (e: Event) => e.stopPropagation(),
          onKeydown: (e: KeyboardEvent) => handleCellNav(e, context.row.index, 'unit_cost'),
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
            disabled: isColumnDisabled.value || isPhantomIndex(context.row.index),
            onClick:
              isColumnDisabled.value || isPhantomIndex(context.row.index)
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
  <div ref="containerRef" class="flex flex-col h-full" tabindex="0" @keydown="onKeydown">
    <div class="flex-1 overflow-y-auto max-h-[60vh]">
      <DataTable
        :columns="columns"
        :data="displayLines"
        @rowClick="(line) => (selectedRowIndex = displayLines.indexOf(line))"
        :page-size="1000"
        :hide-footer="true"
      />
    </div>
  </div>
</template>
