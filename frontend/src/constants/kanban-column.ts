/**
 * UI-specific Kanban Column schema for frontend kanban organization.
 *
 * This schema defines the structure for organizing kanban columns with visual properties
 * such as `colorTheme` and `badgeColorClass` that are not part of the backend API.
 * It is used purely for frontend display and categorization of jobs in KanbanView.
 */

import { z } from 'zod'

export const KanbanColumnSchema = z.object({
  columnId: z.string(),
  columnTitle: z.string(),
  statusKey: z.string(), // Direct 1:1 mapping to job status
  colorTheme: z.string(),
  badgeColorClass: z.string(),
})

export type KanbanColumn = z.infer<typeof KanbanColumnSchema>
