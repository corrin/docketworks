<script setup lang="ts">
import ItemSelect from '@/views/purchasing/ItemSelect.vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { useStockStore } from '@/stores/stockStore'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { fetchCostSet } from '@/services/costing.service'
import { costlineService } from '@/services/costline.service'
import { useCostLineAutosave } from '@/composables/useCostLineAutosave'
import { toast } from 'vue-sonner'
import { Trash2, Wrench } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import { roundToDecimalPlaces } from '@/utils/number'

type CostLine = z.infer<typeof schemas.CostLine>

const props = defineProps<{
  jobId: string
}>()

const stockStore = useStockStore()
const companyDefaultsStore = useCompanyDefaultsStore()

const workshopLines = ref<CostLine[]>([])
const loading = ref(false)
const deletingId = ref<string | null>(null)

const draft = ref<{
  stockId: string | null
  desc: string
  unitCost: number | null
  quantity: number
}>({
  stockId: null,
  desc: '',
  unitCost: null,
  quantity: 1,
})

const creating = ref(false)
const draftKind = ref<'material' | 'adjust'>('material')
const isAdjustDraft = computed(() => draftKind.value === 'adjust')
const showAdjustDialog = ref(false)
const adjustUnitRev = ref<number | null>(null)

function isStockExtRefs(extRefs: unknown): extRefs is { stock_id: string } {
  return (
    typeof extRefs === 'object' &&
    extRefs !== null &&
    'stock_id' in extRefs &&
    typeof (extRefs as Record<string, unknown>).stock_id === 'string'
  )
}

function isDeliveryReceiptLine(line: CostLine): boolean {
  const meta = line.meta as Record<string, unknown> | undefined
  return meta?.source === 'delivery_receipt'
}

function isWorkshopLine(line: CostLine): boolean {
  const kind = String(line.kind)
  return kind === 'material' || kind === 'adjust'
}

function isAdjustLine(line: CostLine): boolean {
  return String(line.kind) === 'adjust'
}

const autosave = useCostLineAutosave({
  debounceMs: 600,
  saveFn: async (id, patch) => {
    return await costlineService.updateCostLine(id, patch)
  },
  onOptimisticApply: (line, patch) => {
    Object.assign(line, patch)
  },
  onRollback: (line, snap) => {
    Object.assign(line, snap)
  },
})

async function loadLines() {
  if (!props.jobId) return
  loading.value = true
  try {
    const costSet = await fetchCostSet(props.jobId, 'actual')
    workshopLines.value = (costSet.cost_lines || []).filter(isWorkshopLine)
  } catch (error) {
    console.error('Failed to load actual material lines:', error)
    toast.error('Failed to load materials used')
    workshopLines.value = []
  } finally {
    loading.value = false
  }
}

function resetDraft(nextKind: 'material' | 'adjust' = 'material') {
  draft.value = { stockId: null, desc: '', unitCost: null, quantity: 1 }
  draftKind.value = nextKind
}

function canEditLine(line: CostLine) {
  if (!line.id) return false
  const kind = String(line.kind)
  if (kind !== 'material' && kind !== 'adjust') return false
  if (kind === 'material' && isDeliveryReceiptLine(line)) return false
  return true
}

async function createFromDraft(selectedStockId: string) {
  if (creating.value) return
  creating.value = true
  try {
    const stock = stockStore.items.find((i) => i.id === selectedStockId)
    if (!stock) {
      throw new Error('Stock item not found')
    }

    const quantity = Number(draft.value.quantity || 1)
    if (!Number.isFinite(quantity) || quantity <= 0) {
      toast.error('Quantity must be greater than 0')
      creating.value = false
      return
    }

    const unitCost = Number(draft.value.unitCost ?? stock.unit_cost ?? 0)
    const unitRev =
      stock.unit_revenue != null
        ? Number(stock.unit_revenue)
        : roundToDecimalPlaces(
            unitCost * (1 + (companyDefaultsStore.companyDefaults?.materials_markup ?? 0)),
            2,
          )

    const now = new Date().toISOString()
    const description =
      draft.value.desc?.trim() || stock.description?.trim() || stock.item_code || 'Material'

    const created = await costlineService.createCostLine(props.jobId, 'actual', {
      kind: 'material',
      desc: description,
      quantity,
      unit_cost: unitCost,
      unit_rev: unitRev,
      accounting_date: now.split('T')[0],
      ext_refs: { stock_id: selectedStockId },
      meta: { source: 'workshop_materials' },
    })

    workshopLines.value = [...workshopLines.value, created].filter(isWorkshopLine)

    toast.success('Material logged for approval')
    resetDraft('material')
  } catch (error) {
    console.error('Failed to add material line:', error)
    toast.error('Failed to add material')
  } finally {
    creating.value = false
  }
}

async function createAdjustFromDraft(unitRevOverride?: number | null) {
  if (creating.value) return
  if (!isAdjustDraft.value) return
  const description = draft.value.desc?.trim()
  if (!description) {
    toast.error('Description is required for adjustments')
    return
  }

  const quantity = Number(draft.value.quantity ?? 0)
  if (!Number.isFinite(quantity) || quantity === 0) {
    toast.error('Quantity must be different from 0')
    return
  }

  creating.value = true
  try {
    const unitRev = Number(unitRevOverride ?? 0)
    if (!Number.isFinite(unitRev)) {
      toast.error('Unit revenue must be a valid number')
      creating.value = false
      return
    }
    const markup = Number(companyDefaultsStore.companyDefaults?.materials_markup ?? 0)
    const unitCost = markup > 0 ? unitRev / (1 + markup) : unitRev
    const normalizedUnitCost = roundToDecimalPlaces(unitCost, 2)
    const normalizedUnitRev = roundToDecimalPlaces(unitRev, 2)
    draft.value.unitCost = normalizedUnitCost
    const now = new Date().toISOString()

    const created = await costlineService.createCostLine(props.jobId, 'actual', {
      kind: 'adjust',
      desc: description,
      quantity,
      unit_cost: normalizedUnitCost,
      unit_rev: normalizedUnitRev,
      accounting_date: now.split('T')[0],
      meta: { source: 'workshop_materials_adjustment' },
    })

    workshopLines.value = [...workshopLines.value, created].filter(isWorkshopLine)
    toast.success('Adjustment added')
    resetDraft('adjust')
  } catch (error) {
    console.error('Failed to add adjustment line:', error)
    toast.error('Failed to add adjustment')
  } finally {
    creating.value = false
  }
}

function openAdjustDialog() {
  if (creating.value || !isAdjustDraft.value) return
  adjustUnitRev.value = null
  showAdjustDialog.value = true
}

async function confirmAdjustDialog() {
  if (creating.value || !isAdjustDraft.value) return
  showAdjustDialog.value = false
  await createAdjustFromDraft(adjustUnitRev.value)
}

async function deleteLine(line: CostLine) {
  if (!line.id) return
  if (deletingId.value) return

  const confirmed = window.confirm('Delete this line? This action cannot be undone.')
  if (!confirmed) return

  deletingId.value = String(line.id)
  try {
    await costlineService.deleteCostLine(String(line.id))
    workshopLines.value = workshopLines.value.filter((l) => String(l.id) !== String(line.id))
    toast.success('Line deleted')
  } catch (error) {
    console.error('Failed to delete cost line:', error)
    toast.error('Failed to delete line')
  } finally {
    deletingId.value = null
  }
}

function stockIdForLine(line: CostLine): string | null {
  return isStockExtRefs(line.ext_refs) ? line.ext_refs.stock_id : null
}

function matchedStockForLine(line: CostLine) {
  if (isAdjustLine(line)) return null
  const stockId = stockIdForLine(line)
  if (stockId) return stockStore.items.find((i) => i.id === stockId) ?? null

  // Delivery receipt lines may not have a stock_id; best-effort match by description.
  const desc = (line.desc ?? '').trim()
  if (!desc) return null
  return stockStore.items.find((i) => (i.description ?? '').trim() === desc) ?? null
}

function itemCodeForLine(line: CostLine): string | null {
  if (isAdjustLine(line)) return null
  return matchedStockForLine(line)?.item_code ?? null
}

onMounted(async () => {
  if (!companyDefaultsStore.isLoaded && !companyDefaultsStore.isLoading) {
    await companyDefaultsStore.loadCompanyDefaults()
  }
  if (stockStore.items.length === 0 && !stockStore.loading) {
    void stockStore.fetchStock()
  }

  await loadLines()
})

watch(
  () => props.jobId,
  () => void loadLines(),
)
</script>

<template>
  <Card>
    <CardHeader>
      <CardTitle class="flex items-center gap-2">
        <Wrench class="h-5 w-5" />
        Materials used
      </CardTitle>
    </CardHeader>

    <CardContent>
      <div v-if="loading" class="space-y-3">
        <Skeleton class="h-10 w-full" />
        <Skeleton class="h-10 w-full" />
        <Skeleton class="h-10 w-full" />
      </div>

      <div v-else class="rounded-md border overflow-x-hidden">
        <Table class="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead class="w-[9rem] sm:w-[12rem]">Item</TableHead>
              <TableHead>Description</TableHead>
              <TableHead class="w-[5.5rem] sm:w-[7rem] text-right">Qty</TableHead>
              <TableHead class="w-[3.5rem] sm:w-[4.5rem] text-center"> </TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            <TableRow v-if="workshopLines.length === 0">
              <TableCell colspan="4" class="py-8 text-center text-sm text-muted-foreground">
                No materials recorded yet.
              </TableCell>
            </TableRow>

            <TableRow v-for="line in workshopLines" :key="String(line.id)">
              <TableCell class="align-top overflow-hidden">
                <div class="min-h-10 flex items-center min-w-0 w-full">
                  <div class="flex flex-col min-w-0 w-full">
                    <div class="flex items-center gap-2">
                      <span
                        v-if="!isAdjustLine(line)"
                        class="font-mono text-sm font-semibold max-w-[6.5rem] sm:max-w-[9rem] truncate"
                        :title="itemCodeForLine(line) ?? ''"
                      >
                        {{ itemCodeForLine(line) ?? '-' }}
                      </span>
                      <Badge v-else variant="secondary" class="text-[11px]"> Adjustment </Badge>
                      <span v-if="isAdjustLine(line)" class="text-xs text-muted-foreground">
                        Manual
                      </span>
                      <span
                        v-else-if="isDeliveryReceiptLine(line)"
                        class="text-xs text-muted-foreground"
                      >
                        Delivery receipt
                      </span>
                      <span v-else class="text-xs text-muted-foreground">Stock</span>
                    </div>
                    <div
                      class="text-xs text-muted-foreground min-w-0 w-full break-words line-clamp-2"
                    >
                      {{ matchedStockForLine(line)?.description ?? (line.desc || '-') }}
                    </div>
                  </div>
                </div>
              </TableCell>

              <TableCell class="align-top">
                <Textarea
                  :model-value="line.desc ?? ''"
                  :disabled="!canEditLine(line)"
                  rows="1"
                  class="min-h-10 text-sm leading-5"
                  @update:model-value="(v) => (line.desc = String(v))"
                  @blur="
                    () => {
                      if (!canEditLine(line)) return
                      autosave.onBlurSave(
                        line,
                        { desc: line.desc ?? '' },
                        { desc: line.desc ?? '' },
                      )
                    }
                  "
                />
              </TableCell>

              <TableCell class="align-top">
                <div class="min-h-10 flex items-start justify-end">
                  <Input
                    type="number"
                    :min="isAdjustLine(line) ? undefined : '0.0000001'"
                    step="1"
                    inputmode="decimal"
                    class="w-20 sm:w-24 text-right"
                    :disabled="!canEditLine(line)"
                    :model-value="line.quantity ?? 0"
                    @update:model-value="(v) => (line.quantity = Number(v))"
                    @blur="
                      () => {
                        if (!canEditLine(line)) return
                        const qty = Number(line.quantity ?? 0)
                        const isAdjust = isAdjustLine(line)
                        if (
                          !Number.isFinite(qty) ||
                          (!isAdjust && qty <= 0) ||
                          (isAdjust && qty === 0)
                        ) {
                          toast.error(
                            isAdjust
                              ? 'Quantity must be different from 0'
                              : 'Quantity must be greater than 0',
                          )
                          return
                        }
                        autosave.onBlurSave(line, { quantity: qty }, { quantity: qty })
                      }
                    "
                  />
                </div>
              </TableCell>

              <TableCell class="align-top">
                <div class="min-h-10 flex items-start justify-center">
                  <Button
                    variant="outline"
                    size="icon"
                    class="h-9 w-9 sm:h-10 sm:w-10 text-red-600 hover:text-red-700 hover:bg-red-50"
                    :disabled="!!deletingId"
                    :aria-label="`Delete line ${String(line.id)}`"
                    @click="deleteLine(line)"
                  >
                    <Trash2 v-if="deletingId !== String(line.id)" class="h-4 w-4" />
                    <svg v-else class="h-4 w-4 animate-spin" viewBox="0 0 24 24">
                      <circle
                        class="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        stroke-width="4"
                        fill="none"
                      />
                      <path
                        class="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                  </Button>
                </div>
              </TableCell>
            </TableRow>

            <!-- Draft row -->
            <TableRow>
              <TableCell class="align-top">
                <div class="min-h-10 flex items-center">
                  <template v-if="!isAdjustDraft">
                    <ItemSelect
                      :model-value="draft.stockId"
                      :disabled="creating"
                      :show-quantity="false"
                      tab-kind="actual"
                      line-kind="material"
                      @update:model-value="
                        (val) => {
                          draft.stockId = val as string | null
                          draftKind = 'material'
                          if (draft.stockId) void createFromDraft(draft.stockId)
                        }
                      "
                      @update:description="(d) => (draft.desc = d)"
                      @update:unit_cost="(c) => (draft.unitCost = c ?? null)"
                    />
                  </template>
                  <template v-else>
                    <div class="flex items-center gap-2">
                      <Badge variant="secondary" class="text-xs">Adjustment</Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-8 px-2 text-xs"
                        :disabled="creating"
                        @click="
                          () => {
                            draftKind = 'material'
                            draft.desc = ''
                          }
                        "
                      >
                        Use item
                      </Button>
                    </div>
                  </template>
                </div>
              </TableCell>

              <TableCell class="align-top">
                <Textarea
                  :model-value="draft.desc"
                  rows="1"
                  class="min-h-10"
                  :disabled="creating"
                  :placeholder="
                    isAdjustDraft ? 'Describe adjustment' : 'Select an item or type an adjustment'
                  "
                  @update:model-value="
                    (v) => {
                      draft.desc = String(v)
                      if (!draft.stockId && draft.desc.trim()) {
                        draftKind = 'adjust'
                      }
                    }
                  "
                  @keydown.enter.prevent="openAdjustDialog"
                />
              </TableCell>

              <TableCell class="align-top">
                <div class="min-h-10 flex items-start justify-end">
                  <Input
                    type="number"
                    :min="isAdjustDraft ? undefined : '0.0000001'"
                    step="1"
                    inputmode="decimal"
                    class="w-20 sm:w-24 text-right"
                    :disabled="creating"
                    :model-value="draft.quantity"
                    @update:model-value="(v) => (draft.quantity = Number(v))"
                    @keydown.enter.prevent="openAdjustDialog"
                  />
                </div>
              </TableCell>

              <TableCell class="align-top">
                <div class="min-h-10 flex items-start justify-center">
                  <Button
                    v-if="isAdjustDraft"
                    variant="default"
                    size="sm"
                    class="h-9"
                    :disabled="creating"
                    @click="openAdjustDialog"
                  >
                    {{ creating ? 'Adding...' : 'Add' }}
                  </Button>
                  <div v-else class="text-sm text-muted-foreground">
                    {{ creating ? 'Adding...' : '' }}
                  </div>
                </div>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </CardContent>
  </Card>

  <Dialog :open="showAdjustDialog" @update:open="showAdjustDialog = $event">
    <DialogContent class="sm:max-w-sm">
      <DialogHeader>
        <DialogTitle>Add adjustment</DialogTitle>
      </DialogHeader>

      <div class="space-y-3">
        <div class="text-sm text-muted-foreground">Set the unit revenue for this adjustment.</div>
        <Input
          type="number"
          step="0.01"
          inputmode="decimal"
          class="w-full text-right"
          :model-value="adjustUnitRev ?? ''"
          @update:model-value="
            (v) => {
              if (v === '') {
                adjustUnitRev = null
                return
              }
              const num = Number(v)
              adjustUnitRev = Number.isNaN(num) ? null : num
            }
          "
          @keydown.enter.prevent="confirmAdjustDialog"
        />
      </div>

      <DialogFooter class="gap-2 sm:gap-0">
        <Button variant="outline" @click="showAdjustDialog = false">Cancel</Button>
        <Button :disabled="creating" @click="confirmAdjustDialog">
          {{ creating ? 'Adding...' : 'Add adjustment' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
/* The shadcn table wrapper has overflow:auto by default; keep vertical overflow but avoid horizontal scrolling. */
:deep([data-slot='table-container']) {
  overflow-x: hidden;
}

/* ItemSelect has a hard min-width; override in this table to stay tablet-friendly. */
:deep(.min-w-64) {
  min-width: 0 !important;
}
</style>
