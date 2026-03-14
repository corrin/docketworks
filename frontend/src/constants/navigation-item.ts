/**
 * Navigation item constant
 *
 * UI structure for navigation items, that defines the shape of navigation data for frontend routing.
 */

import { z } from 'zod'

/**
 * Schema for navigation items
 */
export const NavigationItemSchema = z.object({
  name: z.string(),
  to: z.string(),
  label: z.string(),
})

export type NavigationItem = z.infer<typeof NavigationItemSchema>
