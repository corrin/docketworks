import { schemas } from '../api/generated/api'
import { api } from '@/api/client'
import type { z } from 'zod'

// Generate TypeScript types from Zod schemas
export type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>
export type PatchedCompanyDefaults = z.infer<typeof schemas.PatchedCompanyDefaultsRequest>
export type AIProvider = z.infer<typeof schemas.AIProvider>

export async function getCompanyDefaults(): Promise<CompanyDefaults> {
  return await api.api_company_defaults_retrieve()
}

export async function updateCompanyDefaults(
  payload: Partial<PatchedCompanyDefaults>,
): Promise<CompanyDefaults> {
  return await api.api_company_defaults_partial_update(payload)
}
