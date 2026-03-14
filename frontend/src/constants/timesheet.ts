/**
 * UI-specific constants for timesheet calculations.
 * This file defines the shape of timesheet entries metadata for frontend interactions.
 * NOT RELATED TO BACKEND SCHEMAS.
 */

import { z } from 'zod'
import { schemas } from '../api/generated/api'

/**
 * Schema for timesheet entry metadata (UI-specific extension of backend schema).
 */
export const TimesheetEntryWithMetaSchema = schemas.TimesheetCostLine.extend({
  tempId: z.string().optional(),
  _isSaving: z.boolean().optional(),
  isSaving: z.boolean().optional(),
  isNewRow: z.boolean().optional(),
  isEmptyRow: z.boolean().optional(),
  isModified: z.boolean().optional(),
  jobId: z.string().optional(),
  jobNumber: z.string().optional(),
  jobName: z.string().optional(),
  client: z.string().optional(),
  description: z.string().optional(),
  hours: z.number().optional(),
  bill: z.number().optional(),
  billable: z.boolean().optional(),
  wage: z.number().optional(),
  wageRate: z.number().optional(),
  chargeOutRate: z.number().optional(),
  rateMultiplier: z.number().optional(),
  rate: z.string().optional(),
  staffId: z.string().optional(),
  staffName: z.string().optional(),
  date: z.string().optional(),
  xeroPayItemId: z.string().uuid().optional(),
  xeroPayItemName: z.string().optional(),
})

export type TimesheetEntryWithMeta = z.infer<typeof TimesheetEntryWithMetaSchema>

export type TimesheetEntryJobSelectionItem = Pick<
  z.infer<typeof schemas.ModernTimesheetJob>,
  | 'id'
  | 'job_number'
  | 'name'
  | 'client_name'
  | 'status'
  | 'charge_out_rate'
  | 'default_xero_pay_item_id'
  | 'default_xero_pay_item_name'
>
