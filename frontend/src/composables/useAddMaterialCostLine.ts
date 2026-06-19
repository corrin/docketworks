import type { Ref } from 'vue'
import { toast } from 'vue-sonner'
import { costlineService } from '../services/costline.service'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'
import { toLocalDateString } from '../utils/dateUtils'
import { useSaveFeedback } from '@/composables/useSaveFeedback'
import { requiredNumber } from '@/utils/requiredNumber'

type CostLine = z.infer<typeof schemas.CostLine>
type CostLineCreateUpdate = z.infer<typeof schemas.CostLineCreateUpdateRequest>
type CostSetKind = 'estimate' | 'quote' | 'actual'
type MaterialCostLineInput = Pick<
  CostLine,
  'kind' | 'desc' | 'quantity' | 'unit_cost' | 'unit_rev' | 'ext_refs' | 'meta'
> & { kind: 'material' }

export interface UseAddMaterialCostLineOptions {
  costLines: Ref<CostLine[]>
  jobId: string
  costSetKind: CostSetKind
  isLoading?: Ref<boolean>
  beforeAdd?: () => boolean // Return false to prevent adding
  onSuccess?: (created: CostLine) => void | Promise<void>
}

export function useAddMaterialCostLine(options: UseAddMaterialCostLineOptions) {
  const { costLines, jobId, costSetKind, isLoading, beforeAdd, onSuccess } = options
  const saveFeedback = useSaveFeedback(`job-material-create:${costSetKind}:${jobId}`, {
    toastErrors: false,
  })

  /**
   * Add a material cost line
   */
  async function handleAddMaterial(payload: MaterialCostLineInput) {
    // Run pre-add check if provided
    if (beforeAdd && !beforeAdd()) {
      return
    }

    // Validate payload
    if (!payload || payload.kind !== 'material') return

    if (isLoading) isLoading.value = true
    saveFeedback.saving()

    try {
      const accountingDate = toLocalDateString()
      const createPayload: CostLineCreateUpdate = {
        kind: 'material' as const,
        desc: payload.desc,
        quantity: requiredNumber(payload.quantity, 'material quantity'),
        unit_cost: requiredNumber(payload.unit_cost, 'material unit_cost'),
        unit_rev: requiredNumber(payload.unit_rev, 'material unit_rev'),
        accounting_date: accountingDate,
        ext_refs: (payload.ext_refs as Record<string, unknown>) || {},
        meta: (payload.meta as Record<string, unknown>) || {},
      }

      const created = await costlineService.createCostLine(jobId, costSetKind, createPayload)

      // Add to cost lines array
      costLines.value = [...costLines.value, created as CostLine]

      saveFeedback.saved()

      // Call success callback if provided
      if (onSuccess) {
        await onSuccess(created as CostLine)
      }

      return created
    } catch (error) {
      saveFeedback.error('Failed to add material cost line.')
      toast.error('Failed to add material cost line.')
      console.error('Failed to add material:', error)
      throw error
    } finally {
      if (isLoading) isLoading.value = false
    }
  }

  return {
    handleAddMaterial,
  }
}
