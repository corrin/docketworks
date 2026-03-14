<script setup lang="ts">
import { computed, h } from 'vue'
import DataTable from '../DataTable.vue'
import { Button } from '../ui/button'
import { Checkbox } from '../ui/checkbox'
import { ArrowDown, ArrowDownToLine } from 'lucide-vue-next'
import { schemas } from '../../api/generated/api'
import type { z } from 'zod'
import { formatCurrency } from '@/utils/string-formatting'

// Use generated types from API schema
type PendingLine = z.infer<typeof schemas.PurchaseOrderLine> & {
  job_name?: string
  selected?: boolean
}

interface DataTableRowContext {
  row: {
    original: PendingLine
    index: number
  }
}

type Props = {
  lines: PendingLine[]
  selectedLines: string[]
  isLoading?: boolean
}

type Emits = {
  (e: 'update:selected-lines', lineIds: string[]): void
  (e: 'move-selected-to-received'): void
  (e: 'move-all-to-received'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const allSelected = computed(
  () =>
    props.lines.length > 0 && props.lines.every((line) => props.selectedLines.includes(line.id)),
)

const columns = computed(() => [
  {
    id: 'select',
    header: () =>
      h(Checkbox, {
        modelValue: allSelected.value,
        'onUpdate:modelValue': (checked: boolean | 'indeterminate') => {
          if (checked === true) {
            emit(
              'update:selected-lines',
              props.lines.map((line) => line.id),
            )
          } else {
            emit('update:selected-lines', [])
          }
        },
        class: 'mx-auto',
      }),
    cell: ({ row }: DataTableRowContext) =>
      h(Checkbox, {
        modelValue: props.selectedLines.includes(row.original.id),
        'onUpdate:modelValue': (checked: boolean | 'indeterminate') => {
          const newSelection =
            checked === true
              ? [...props.selectedLines, row.original.id]
              : props.selectedLines.filter((id) => id !== row.original.id)
          emit('update:selected-lines', newSelection)
        },
        class: 'mx-auto',
      }),
    meta: { editable: true },
  },
  {
    id: 'job_name',
    header: 'Job',
    accessorKey: 'job_name',
    cell: ({ row }: DataTableRowContext) => row.original.job_name || 'N/A',
  },
  {
    id: 'description',
    header: 'Description',
    accessorKey: 'description',
  },
  {
    id: 'remaining_quantity',
    header: 'Remaining',
    cell: ({ row }: DataTableRowContext) => {
      const quantity = row.original.quantity || 0
      const receivedQuantity = row.original.received_quantity || 0
      const remaining = quantity - receivedQuantity
      return remaining.toFixed(2)
    },
  },
  {
    id: 'unit_cost',
    header: 'Unit Cost',
    cell: ({ row }: DataTableRowContext) => {
      const unitCost = row.original.unit_cost
      return unitCost ? formatCurrency(unitCost) : 'N/A'
    },
  },
])
</script>

<template>
  <div class="space-y-4">
    <!-- Action Buttons -->
    <div class="flex gap-2 justify-center">
      <Button
        @click="emit('move-selected-to-received')"
        :disabled="selectedLines.length === 0"
        class="flex items-center gap-2"
      >
        <ArrowDown class="w-4 h-4" />
        Move Selected to Received
      </Button>
      <Button
        @click="emit('move-all-to-received')"
        variant="secondary"
        :disabled="lines.length === 0"
        class="flex items-center gap-2"
      >
        <ArrowDownToLine class="w-4 h-4" />
        Move All to Received
      </Button>
    </div>

    <!-- Data Table -->
    <div class="border rounded-lg">
      <DataTable
        :columns="columns"
        :data="lines"
        @rowClick="() => {}"
        :page-size="1000"
        :hide-footer="true"
        class="min-h-[200px]"
      />

      <!-- Loading State -->
      <div v-if="lines.length === 0 && isLoading" class="p-8 text-center text-gray-500">
        <div class="flex items-center justify-center gap-2 mb-2">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          <div class="text-lg font-medium">Loading pending items</div>
        </div>
        <div class="text-sm">Please wait while we fetch the data</div>
      </div>

      <!-- Empty State -->
      <div v-if="lines.length === 0 && !isLoading" class="p-8 text-center text-gray-500">
        <div class="text-lg font-medium">No pending items</div>
        <div class="text-sm">All items have been received</div>
      </div>
    </div>
  </div>
</template>
