import { schemas } from '@/api/generated/api'
import { z } from 'zod'

type CostSet = z.infer<typeof schemas.CostSet>
type CostSetSummaryOnly = z.infer<typeof schemas.CostSetSummaryOnly>
type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

function getCostSetHours(costSet?: CostSet | CostSetSummaryOnly | null): number {
  if (!costSet) return 0

  const summaryHours = costSet.summary?.hours
  if (typeof summaryHours === 'number' && Number.isFinite(summaryHours)) {
    return summaryHours
  }

  if (!Array.isArray(costSet.cost_lines)) return 0
  return costSet.cost_lines.reduce((sum: number, line: unknown) => {
    const qty = (line as { quantity?: number })?.quantity || 0
    return sum + qty
  }, 0)
}

export function getJobEstimatedHours(job: Job | JobSummary): number {
  if (!job) return 0

  const methodology = job.pricing_methodology ?? 'time_materials'
  const estimateHours = getCostSetHours(job.latest_estimate ?? null)
  const quoteHours = getCostSetHours(job.latest_quote ?? null)

  if (methodology === 'fixed_price') {
    if (quoteHours > 0) return quoteHours
    if (estimateHours > 0) return estimateHours
    return quoteHours
  }

  if (estimateHours > 0) return estimateHours
  if (quoteHours > 0) return quoteHours
  return estimateHours
}

export function getJobActualHours(job: Job | JobSummary): number {
  if (!job) return 0
  return getCostSetHours(job.latest_actual ?? null)
}

export function getCostSetHoursSafe(costSet?: CostSet | CostSetSummaryOnly | null): number {
  return getCostSetHours(costSet)
}
