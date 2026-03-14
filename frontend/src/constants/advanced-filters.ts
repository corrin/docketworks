/**
 * Advanced Search Filter Constants
 *
 * UI structure for the advanced search dialog form.
 * This defines the shape of filter data for frontend form handling.
 */

import { z } from 'zod'

/**
 * Schema for advanced search filters
 */
export const AdvancedFiltersSchema = z.object({
  q: z.string().optional().default(''), // Universal search across multiple fields
  job_number: z.string().optional().default(''),
  name: z.string().optional().default(''),
  description: z.string().optional().default(''),
  client_name: z.string().optional().default(''),
  contact_person: z.string().optional().default(''),
  created_by: z.string().optional().default(''),
  status: z.array(z.string()).optional().default([]),
  created_after: z.string().optional().default(''),
  created_before: z.string().optional().default(''),
  paid: z.string().optional().default(''),
  rejected_flag: z.string().optional().default(''),
  xero_invoice_params: z.string().optional().default(''),
})

export type AdvancedFilters = z.infer<typeof AdvancedFiltersSchema>

/**
 * Default empty filter state
 */
export const DEFAULT_ADVANCED_FILTERS: AdvancedFilters = {
  q: '',
  job_number: '',
  name: '',
  description: '',
  client_name: '',
  contact_person: '',
  created_by: '',
  status: [],
  created_after: '',
  created_before: '',
  paid: '',
  rejected_flag: '',
  xero_invoice_params: '',
}
