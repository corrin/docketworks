import { computed, type Ref } from 'vue'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'

type CostLine = z.infer<typeof schemas.CostLine>

export type CostSummary = {
  cost: number
  rev: number
  hours: number
  profitMargin: number
  created?: string | null
} & Record<string, unknown>

export interface UseCostSummaryOptions {
  costLines: Ref<CostLine[]>
  includeAdjustments?: boolean // Whether to include 'adjust' lines in calculations
}

export function useCostSummary(options: UseCostSummaryOptions) {
  const { costLines, includeAdjustments = true } = options

  /**
   * Computed summary of cost lines
   */
  const summary = computed<CostSummary>(() => {
    let cost = 0
    let rev = 0
    let hours = 0

    for (const line of costLines.value) {
      const quantity = line.quantity || 0
      const unitCost = line.unit_cost || 0
      const unitRev = line.unit_rev || 0

      if (line.kind === 'time') {
        cost += quantity * unitCost
        rev += quantity * unitRev
        hours += quantity
      } else if (line.kind === 'material') {
        cost += quantity * unitCost
        rev += quantity * unitRev
      } else if (line.kind === 'adjust' && includeAdjustments) {
        // Adjustments typically affect cost and rev but not hours
        cost += quantity * unitCost
        rev += quantity * unitRev
      }
    }

    return {
      cost,
      rev,
      hours,
      profitMargin: rev - cost,
      created: undefined,
    }
  })

  /**
   * Alternative summary calculation (simpler version for ActualTab)
   * Counts all lines regardless of type
   */
  const simpleSummary = computed<CostSummary>(() => {
    let cost = 0
    let rev = 0
    let hours = 0

    for (const line of costLines.value) {
      const quantity = line.quantity || 0
      const unitCost = line.unit_cost || 0
      const unitRev = line.unit_rev || 0

      cost += quantity * unitCost
      rev += quantity * unitRev

      // Count hours only for time entries
      if (line.kind === 'time') {
        hours += quantity
      }
    }

    return {
      cost,
      rev,
      hours,
      profitMargin: rev - cost,
    }
  })

  return {
    summary,
    simpleSummary,
  }
}
