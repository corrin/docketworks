/**
 * UI constants for drag-and-drop functionality.
 * This defines the shape of drag-and-drop data for frontend interactions.
 */

import { z } from 'zod'

export const DragEventDataSchema = z.object({
  jobId: z.string(),
  fromStatus: z.string(),
  toStatus: z.string(),
})

export const JobCardElement = z.object({
  id: z.string(),
  classes: z.string(),
  hasDataId: z.boolean(),
})

export const SortableOptionsSchema = z.object({
  group: z.string(),
  animation: z.number(),
  ghostClass: z.string(),
  chosenClass: z.string(),
  dragClass: z.string(),
  draggable: z.string(),
  disabled: z.boolean(),
  delay: z.number(),
  touchStartThreshold: z.number(),
})

export type DragEventData = z.infer<typeof DragEventDataSchema>
export type JobCardElement = z.infer<typeof JobCardElement>
export type SortableOptions = z.infer<typeof SortableOptionsSchema>
