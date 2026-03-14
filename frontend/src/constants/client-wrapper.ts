/**
 * The following schema is purely used in UI - it's a wrapper around the backend schema to help with
 * frontend flow control (to allow a simple try-catch and an uniform flow).
 * It is not used in the backend and does not need to be defined in the backend schema.
 */

import { z } from 'zod'
import { schemas } from '@/api/generated/api'

export const CreateClientResponseSchema = z.object({
  success: z.boolean(),
  client: schemas.ClientSearchResult.optional(),
  error: z.string().optional(),
  message: z.string().optional(),
})

export type CreateClientResponse = z.infer<typeof CreateClientResponseSchema>
