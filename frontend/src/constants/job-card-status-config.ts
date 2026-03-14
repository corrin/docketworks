/**
 * Job Card Constants
 *
 * Purely visual configuration (variant + tailwind class) for job card status.
 * This defines the shape of job card status configuration for frontend display.
 * No business logic or API interaction is involved, just UI-related.
 */

import { z } from 'zod'

export const JobCardStatusConfigSchema = z.object({
  variant: z.enum(['default', 'secondary', 'outline']),
  borderClass: z.string(),
})

export type JobCardStatusConfig = z.infer<typeof JobCardStatusConfigSchema>
