/**
 * UI-specific type definition for the vue-advanced-chat component.
 *
 * @remarks
 * The vue-advanced-chat component expects messages in a specific format,
 * which differs from the API's {@link JobQuoteChat} structure.
 * This type is used to adapt data for proper display in the chat UI.
 */

import { z } from 'zod'

export const VueChatMessageSchema = z.object({
  _id: z.string(),
  content: z.string(),
  senderId: z.string(),
  username: z.string(),
  timestamp: z.string(),
  system: z.boolean(),
  metadata: z.record(z.unknown()).optional(),
})

export type VueChatMessage = z.infer<typeof VueChatMessageSchema>
