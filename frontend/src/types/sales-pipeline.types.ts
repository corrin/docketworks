import { z } from 'zod'
import { schemas } from '@/api/generated/api'

export interface SalesPipelineReportParams {
  start_date: string
  end_date?: string
  rolling_window_weeks?: number
  trend_weeks?: number
}

export type SalesPipelinePeriod = z.infer<typeof schemas.SalesPipelinePeriod>
export type SalesPipelineSnapshotJob = z.infer<typeof schemas.SalesPipelineSnapshotJob>
export type SalesPipelineStageBucket = z.infer<typeof schemas.SalesPipelineStageBucket>
export type SalesPipelineSnapshot = z.infer<typeof schemas.SalesPipelineSnapshot>
export type SalesPipelineVelocityMetric = z.infer<typeof schemas.SalesPipelineVelocityMetric>
export type SalesPipelineVelocity = z.infer<typeof schemas.SalesPipelineVelocity>
export type SalesPipelineFunnelBucket = z.infer<typeof schemas.SalesPipelineFunnelBucket>
export type SalesPipelineFunnel = z.infer<typeof schemas.SalesPipelineFunnel>
export type SalesPipelineTrendWeek = z.infer<typeof schemas.SalesPipelineTrendWeek>
export type SalesPipelineRollingPoint = z.infer<typeof schemas.SalesPipelineRollingPoint>
export type SalesPipelineTrend = z.infer<typeof schemas.SalesPipelineTrend>
export type SalesPipelineWarningSampleJob = z.infer<typeof schemas.SalesPipelineWarningSampleJob>
export type SalesPipelineWarning = z.infer<typeof schemas.SalesPipelineWarning>

// New scoreboard sub-shapes (added by backend in the same redesign branch).
//
// The generated zod schemas have not been regenerated yet at the time of this
// edit (`npm run update-schema && npm run gen:api` is the user's job, not this
// agent's). The Vue file relies on these fields, so we declare explicit
// interfaces here that match `SalesPipelineScoreboardSerializer` exactly.
export interface SalesPipelineSizeBucket {
  count: number
  hours: number
  hours_per_working_day: number | null
  share_of_hours: number | null
}
export interface SalesPipelineSizeBuckets {
  small: SalesPipelineSizeBucket
  medium: SalesPipelineSizeBucket
  large: SalesPipelineSizeBucket
}
export interface SalesPipelineFunnelPath {
  count: number
  hours: number
  hours_per_working_day: number | null
}
export interface SalesPipelineFunnelPaths {
  instant: SalesPipelineFunnelPath
  estimating: SalesPipelineFunnelPath
}

// Scoreboard re-declared so we get the new fields without waiting on
// the generated schema. The generated `SalesPipelineScoreboard` is a strict
// subset of this type.
export interface SalesPipelineScoreboard {
  approved_hours_total: number
  approved_hours_per_working_day: number | null
  approved_jobs_count: number
  direct_hours: number
  direct_jobs_count: number
  working_days: number
  target_hours_for_period: number
  pace_vs_target: number | null
  by_size_bucket: SalesPipelineSizeBuckets
  by_funnel_path: SalesPipelineFunnelPaths
}

export interface SalesPipelineResponse {
  period: SalesPipelinePeriod
  scoreboard: SalesPipelineScoreboard
  pipeline_snapshot: SalesPipelineSnapshot
  velocity: SalesPipelineVelocity
  conversion_funnel: SalesPipelineFunnel
  trend: SalesPipelineTrend
  warnings: SalesPipelineWarning[]
}
