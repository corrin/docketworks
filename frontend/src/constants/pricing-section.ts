/**
 * Pricing Section Constants
 *
 * UI structure for pricing section forms (estimates, quotes, reality).
 * This defines the shape of pricing data for frontend form handling.
 */

import { z } from 'zod'

/**
 * Schema for pricing section
 */
export const PricingSectionSchema = z.object({
  time: z.number().optional().default(0),
  materials: z.number().optional().default(0),
  adjustments: z.number().optional().default(0),
  total: z.number().optional().default(0),
})

export type PricingSection = z.infer<typeof PricingSectionSchema>

/**
 * Default empty pricing section state
 */
export const DEFAULT_PRICING_SECTION: PricingSection = {
  time: -10000,
  materials: -10000,
  adjustments: -10000,
  total: -10000,
}
