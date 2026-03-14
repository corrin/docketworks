/**
 * Date Range Constants
 *
 * UI structure for date range picker components.
 * This defines the shape of date range data for frontend form handling.
 */

import { z } from 'zod'

/**
 * Schema for date range filters
 */
export const DateRangeSchema = z.object({
  from: z.string().optional(),
  to: z.string().optional(),
})

export type DateRange = z.infer<typeof DateRangeSchema>

export type FilterState = {
  search: string
  range: DateRange
}

/**
 * Default empty date range state
 */
export const DEFAULT_DATE_RANGE: DateRange = {
  from: undefined,
  to: undefined,
}
