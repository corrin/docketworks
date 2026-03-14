import type { Ref } from 'vue'
import { toast } from 'vue-sonner'
import { costlineService } from '../services/costline.service'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'
import { debugLog } from '../utils/debug'
import { toLocalDateString } from '../utils/dateUtils'
import { useJobsStore } from '../stores/jobs'

type CostLine = z.infer<typeof schemas.CostLine>
type CostLineCreateUpdate = z.infer<typeof schemas.CostLineCreateUpdateRequest>
type CostSetKind = 'estimate' | 'quote' | 'actual'
type CostLineInput = Pick<
  CostLine,
  'kind' | 'desc' | 'quantity' | 'unit_cost' | 'unit_rev' | 'ext_refs' | 'meta'
>

export interface UseCreateCostLineFromEmptyOptions {
  costLines: Ref<CostLine[]>
  jobId: string
  costSetKind: CostSetKind
  onSuccess?: (created: CostLine) => void | Promise<void>
  beforeCreate?: () => boolean // Return false to prevent creation
}

export function useCreateCostLineFromEmpty(options: UseCreateCostLineFromEmptyOptions) {
  const { costLines, jobId, costSetKind, onSuccess, beforeCreate } = options
  const jobsStore = useJobsStore()

  /**
   * Create a cost line from an empty line that meets baseline criteria
   */
  async function handleCreateFromEmpty(line: CostLineInput) {
    // Run pre-creation check if provided
    if (beforeCreate && !beforeCreate()) {
      return
    }

    debugLog(`Creating cost line from empty line (${costSetKind}):`, line)

    try {
      const accountingDate = toLocalDateString()
      const jobHeader = jobsStore.headersById[jobId]
      const createPayload: CostLineCreateUpdate = {
        kind: line.kind as 'material' | 'time' | 'adjust',
        desc: line.desc || '',
        quantity: line.quantity || 1,
        unit_cost: line.unit_cost ?? 0,
        unit_rev: line.unit_rev ?? 0,
        accounting_date: accountingDate,
        ext_refs: (line.ext_refs as Record<string, unknown>) || {},
        meta: (line.meta as Record<string, unknown>) || {},
        xero_pay_item: line.kind === 'time' ? (jobHeader?.default_xero_pay_item_id ?? null) : null,
      }

      const created = await costlineService.createCostLine(jobId, costSetKind, createPayload)

      // Insert created line into costLines; replace if the source line exists, otherwise push (phantom row case)
      const index = costLines.value.findIndex((l) => l === line)
      if (index !== -1) {
        costLines.value[index] = created as CostLine
      } else {
        // When creating from the table's phantom row (not present in costLines), append it
        costLines.value.push(created as CostLine)
      }

      toast.success('Cost line created!')
      debugLog('Successfully created cost line:', created)

      // Call success callback if provided
      if (onSuccess) {
        await onSuccess(created as CostLine)
      }

      return created
    } catch (error) {
      console.error('Failed to create cost line:', error)
      toast.error('Failed to create cost line')
      throw error
    }
  }

  return {
    handleCreateFromEmpty,
  }
}
