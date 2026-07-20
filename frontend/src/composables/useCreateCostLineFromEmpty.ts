import { toast } from 'vue-sonner'
import { costlineService } from '../services/costline.service'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'
import { debugLog } from '../utils/debug'
import { toLocalDateString } from '../utils/dateUtils'
import { useJobsStore } from '../stores/jobs'
import { useSaveFeedback } from '@/composables/useSaveFeedback'
import { requiredNumber } from '@/utils/requiredNumber'

type CostLine = z.infer<typeof schemas.CostLine>
type CostLineCreateUpdate = z.infer<typeof schemas.CostLineCreateUpdateRequest>
type CostSetKind = 'estimate' | 'quote' | 'actual'
type CostLineInput = Pick<
  CostLine,
  'kind' | 'desc' | 'quantity' | 'unit_cost' | 'unit_rev' | 'ext_refs' | 'meta' | 'labour_subtype'
>

export interface UseCreateCostLineFromEmptyOptions {
  jobId: string
  costSetKind: CostSetKind
  onSuccess?: (created: CostLine) => void | Promise<void>
  beforeCreate?: () => boolean // Return false to prevent creation
}

export function useCreateCostLineFromEmpty(options: UseCreateCostLineFromEmptyOptions) {
  const { jobId, costSetKind, onSuccess, beforeCreate } = options
  const jobsStore = useJobsStore()
  const saveFeedback = useSaveFeedback(`job-cost-line-create:${costSetKind}:${jobId}`, {
    toastErrors: false,
  })

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
      saveFeedback.saving()
      const accountingDate = toLocalDateString()
      const jobHeader = jobsStore.headersById[jobId]
      const createPayload: CostLineCreateUpdate = {
        kind: line.kind as 'material' | 'time' | 'adjust',
        desc: line.desc || '',
        quantity: requiredNumber(line.quantity, 'cost line quantity'),
        unit_cost: requiredNumber(line.unit_cost, 'cost line unit_cost'),
        unit_rev: requiredNumber(line.unit_rev, 'cost line unit_rev'),
        accounting_date: accountingDate,
        ext_refs: (line.ext_refs as Record<string, unknown>) || {},
        meta: (line.meta as Record<string, unknown>) || {},
        xero_pay_item: line.kind === 'time' ? (jobHeader?.default_xero_pay_item_id ?? null) : null,
        // The API requires labour_subtype on time lines; the table defaults
        // new time lines to the workshop subtype before emitting create-line.
        labour_subtype: line.kind === 'time' ? (line.labour_subtype ?? null) : null,
      }

      const created = await costlineService.createCostLine(jobId, costSetKind, createPayload)

      saveFeedback.saved()
      debugLog('Successfully created cost line:', created)

      // Call success callback if provided
      if (onSuccess) {
        await onSuccess(created as CostLine)
      }

      return created
    } catch (error) {
      console.error('Failed to create cost line:', error)
      saveFeedback.error('Failed to create cost line')
      toast.error('Failed to create cost line')
      throw error
    }
  }

  return {
    handleCreateFromEmpty,
  }
}
