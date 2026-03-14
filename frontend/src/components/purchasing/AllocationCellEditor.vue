<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { History, Plus, Trash2, Zap, Package } from 'lucide-vue-next'
import JobSelect from '@/components/purchasing/JobSelect.vue'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'
import { debugLog } from '../../utils/debug'
import { api } from '../../api/client'

type PurchaseOrderLine = z.infer<typeof schemas.PurchaseOrderLine>
type JobForPurchasing = z.infer<typeof schemas.JobForPurchasing>
type AllocationItem = z.infer<typeof schemas.AllocationItem>
type AllocationDeleteRequest = z.infer<typeof schemas.AllocationDeleteRequest>

interface Props {
  line: PurchaseOrderLine
  poId: string
  jobs: JobForPurchasing[]
  existing: AllocationItem[]
  defaultRetailRate?: number
  stockHoldingJobId?: string
  disabled?: boolean
  poStatus?: string
}
const props = defineProps<Props>()

const emit = defineEmits<{
  save: [editorState: { rows: EditorRow[] }]
  'allocation-deleted': [data: { allocationId: string; allocationType: string }]
}>()

interface EditorRow {
  job_id: string
  quantity: number
  retail_rate?: number
  stock_location?: string
  metal_type?: string
  alloy?: string
  specifics?: string
  dimensions?: string
}

const open = ref(false)
const rows = ref<EditorRow[]>([])
const initialState = ref('')
const isSaving = ref(false) // UK: Guard to prevent duplicate saves.

const isReceiptVisible = computed(() => {
  const validStatuses = [
    'submitted',
    'submitted_to_supplier',
    'partially_received',
    'fully_received',
  ]
  return validStatuses.includes(props.poStatus || '')
})

const thisReceiptTotal = computed(() =>
  rows.value.reduce((s, r) => s + (Number(r.quantity) || 0), 0),
)
const remaining = computed(() => {
  const orderedQuantity = props.line.quantity || 0
  const alreadyReceived = props.line.received_quantity || 0
  return Math.max(0, orderedQuantity - alreadyReceived)
})

const overReceipt = computed(() => thisReceiptTotal.value > remaining.value)
const canAddRow = computed(() => remaining.value > 0 && !overReceipt.value)

const enhancedJobs = computed(() => {
  return props.jobs.map((job) => ({
    ...job,
    isStockHolding: job.id === props.stockHoldingJobId,
    displayName:
      job.id === props.stockHoldingJobId
        ? `📦 ${job.name} (Stock)`
        : `${job.job_number} - ${job.name}`,
  })) as (JobForPurchasing & { isStockHolding: boolean; displayName: string })[]
})

function openEditor() {
  if (props.disabled || !isReceiptVisible.value) return

  if (rows.value.length === 0) {
    const defaultJobId = props.line.job_id || props.stockHoldingJobId
    if (defaultJobId) {
      rows.value.push({
        job_id: defaultJobId,
        quantity: Math.min(remaining.value, props.line.quantity || 1),
        retail_rate: props.defaultRetailRate ?? 0,
      })
    }
  }

  initialState.value = JSON.stringify(rows.value)
  open.value = true

  nextTick(() => {
    const firstInput = document.querySelector('.allocation-quantity-input') as HTMLInputElement
    firstInput?.focus()
  })
}

async function handleSaveAndClose() {
  if (isSaving.value) return // UK: Prevents the function from running again if already saving.
  isSaving.value = true

  const validRows = rows.value.filter((r) => (Number(r.quantity) || 0) > 0 && r.job_id)

  if (overReceipt.value) {
    open.value = false
    isSaving.value = false
    return
  }

  if (validRows.length > 0) {
    const transformedRows = validRows.map((row) => {
      const isStock = row.job_id === props.stockHoldingJobId
      const baseRow: Record<string, unknown> = {
        job_id: row.job_id,
        quantity: row.quantity,
        retail_rate: row.retail_rate,
      }
      if (isStock) {
        baseRow.stock_location = row.stock_location || props.line.location || ''
        baseRow.metal_type = row.metal_type || props.line.metal_type || ''
        baseRow.alloy = row.alloy || props.line.alloy || ''
        baseRow.specifics = row.specifics || props.line.specifics || ''
        baseRow.dimensions = row.dimensions || props.line.dimensions || ''
      }
      return baseRow as unknown as EditorRow
    })
    emit('save', { rows: transformedRows })
  }

  open.value = false
  setTimeout(() => {
    isSaving.value = false
  }, 100) // UK: Release the lock after a short delay.
}

function allocateRemaining() {
  if (!remaining.value) return
  if (rows.value.length === 0) addRow()
  if (rows.value.length > 0) rows.value[0].quantity = remaining.value
}

function handleKeydown(event: KeyboardEvent) {
  if (!open.value) return
  if (event.shiftKey && event.key.toLowerCase() === 'r') allocateRemaining()
  if (event.shiftKey && event.key.toLowerCase() === 'n') if (canAddRow.value) addRow()
  if (event.key === 'Escape') {
    event.preventDefault()
    handleSaveAndClose()
  }
}

function addRow() {
  if (!canAddRow.value) return
  const defaultJobId = props.line.job_id || props.stockHoldingJobId || props.jobs[0]?.id
  if (!defaultJobId) return
  rows.value.push({
    job_id: defaultJobId,
    quantity: Math.min(1, remaining.value),
    retail_rate: props.defaultRetailRate ?? 0,
  })
}

function removeRow(index: number) {
  rows.value.splice(index, 1)
}

function handleJobSelected(rowIndex: number, job: JobForPurchasing | null) {
  if (!job) return
  rows.value[rowIndex].job_id = job.id
}

function isStockHoldingJob(jobId: string): boolean {
  return jobId === props.stockHoldingJobId
}

async function deleteAllocation(allocationId: string, allocationType: 'job' | 'stock') {
  try {
    const payload: AllocationDeleteRequest = {
      allocation_id: allocationId,
      allocation_type: allocationType,
    }
    const response = await api.deleteAllocation(payload, {
      params: { po_id: String(props.poId), line_id: String(props.line.id) },
    })
    if (response.success) {
      emit('allocation-deleted', { allocationId, allocationType })
    } else {
      throw new Error(response.message || 'Failed to delete allocation')
    }
  } catch (error) {
    debugLog('Error deleting allocation:', error)
  }
}

onMounted(() => document.addEventListener('keydown', handleKeydown))
onUnmounted(() => document.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <div class="w-full">
    <Popover v-model:open="open">
      <PopoverTrigger as-child>
        <Button
          size="sm"
          variant="outline"
          :disabled="disabled || !isReceiptVisible"
          @click.stop.prevent="openEditor"
          class="w-full text-xs min-h-[32px] hover:bg-blue-50 transition-colors"
        >
          <div class="flex items-center justify-center gap-2 p-1">
            <Package class="w-3 h-3 text-blue-600" />
            <span class="font-medium text-blue-700">
              {{ existing.length > 0 ? 'Check Allocations' : 'Add Allocation' }}
            </span>
            <span v-if="remaining > 0" class="text-xs text-muted-foreground"
              >({{ remaining }} left)</span
            >
          </div>
        </Button>
      </PopoverTrigger>

      <PopoverContent
        class="p-4 w-[450px] !max-h-[70vh] flex flex-col"
        :side="existing.length > 0 ? 'top' : 'bottom'"
        align="center"
        :side-offset="4"
      >
        <div class="flex items-center justify-between mb-3">
          <div class="text-sm font-medium flex items-center gap-2">
            <Package class="w-4 h-4 text-blue-600" />
            Receipt Allocation
          </div>
          <Button
            class="p-2"
            size="sm"
            variant="ghost"
            :disabled="!remaining"
            @click="allocateRemaining"
            title="Shift+R"
          >
            <Zap class="w-3 h-3 mr-1" />
            Allocate Remaining
          </Button>
        </div>

        <div
          v-if="overReceipt"
          class="p-2 mb-2 text-xs rounded border border-red-200 bg-red-50 text-red-700"
        >
          ⚠️ Exceeds remaining quantity. Changes will not be saved.
        </div>

        <div
          v-if="existing.length > 0"
          class="mb-3 p-2 border rounded-lg bg-blue-50 border-blue-200"
        >
          <div class="flex items-center gap-1 mb-2">
            <History class="w-3 h-3 text-blue-600" />
            <span class="text-xs font-medium text-blue-800">Previous Allocations</span>
          </div>
          <div class="space-y-1">
            <div
              v-for="(alloc, idx) in existing"
              :key="alloc.allocation_id ?? idx"
              class="flex items-center justify-between text-xs bg-white rounded p-2 border"
            >
              <div>
                <div class="font-medium text-gray-800">{{ alloc.job_name || 'Unknown Job' }}</div>
                <div class="text-gray-600">Qty: {{ alloc.quantity }}</div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                @click="
                  deleteAllocation(alloc.allocation_id!, alloc.stock_location ? 'stock' : 'job')
                "
              >
                <Trash2 class="w-3 h-3 text-red-500" />
              </Button>
            </div>
          </div>
        </div>

        <div class="flex-1 overflow-auto pr-1 space-y-3">
          <div
            v-for="(row, idx) in rows"
            :key="idx"
            class="p-3 border rounded-lg bg-gray-50 space-y-3"
          >
            <div class="flex items-start gap-2">
              <div class="flex-1 space-y-1">
                <label class="text-xs font-medium text-gray-700">Job</label>
                <JobSelect
                  :model-value="row.job_id"
                  :jobs="enhancedJobs"
                  @job-selected="(job) => handleJobSelected(idx, job)"
                />
              </div>
              <div class="w-24 space-y-1">
                <label class="text-xs font-medium text-gray-700">Quantity</label>
                <Input
                  type="number"
                  class="allocation-quantity-input text-right"
                  v-model.number="row.quantity"
                  :min="0"
                  :max="remaining + (row.quantity || 0)"
                />
              </div>
              <Button
                size="sm"
                variant="ghost"
                @click="removeRow(idx)"
                class="mt-[21px] text-red-500 hover:text-red-700 hover:bg-red-50"
              >
                <Trash2 class="w-4 h-4" />
              </Button>
            </div>
            <div class="space-y-1">
              <label class="text-xs font-medium text-gray-700">Retail Rate (%)</label>
              <Input
                type="number"
                v-model.number="row.retail_rate"
                min="0"
                max="100"
                step="0.01"
                placeholder="0.00"
              />
            </div>
            <div
              v-if="isStockHoldingJob(row.job_id)"
              class="text-xs text-orange-600 flex items-center gap-1"
            >
              <Package class="w-3 h-3" />
              These items will be added to stock.
            </div>
          </div>
        </div>

        <div class="flex justify-between items-center mt-4 pt-3 border-t">
          <Button
            size="sm"
            variant="outline"
            @click="addRow"
            :disabled="!canAddRow"
            title="Add new allocation (Shift+N)"
          >
            <Plus class="w-3 h-3 mr-1" /> Add
          </Button>
          <Button size="sm" @click="handleSaveAndClose">Done</Button>
        </div>
      </PopoverContent>
    </Popover>
  </div>
</template>
