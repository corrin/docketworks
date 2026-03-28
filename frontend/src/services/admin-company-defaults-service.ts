import { schemas } from '../api/generated/api'
import { api } from '@/api/client'
import type { z } from 'zod'
import { getCsrfToken } from '@/utils/csrf'

// Generate TypeScript types from Zod schemas
export type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>
export type PatchedCompanyDefaults = z.infer<typeof schemas.PatchedCompanyDefaultsRequest>
export type AIProvider = z.infer<typeof schemas.AIProvider>

export async function getCompanyDefaults(): Promise<CompanyDefaults> {
  return await api.company_defaults_retrieve()
}

export async function updateCompanyDefaults(
  payload: Partial<PatchedCompanyDefaults>,
): Promise<CompanyDefaults> {
  return await api.company_defaults_partial_update(payload)
}

// Raw fetch used here because the generated Zodios client does not support multipart form uploads.
export async function uploadLogo(fieldName: string, file: File): Promise<CompanyDefaults> {
  const formData = new FormData()
  formData.append('field_name', fieldName)
  formData.append('file', file)

  const csrfToken = getCsrfToken()
  const response = await fetch('/api/company-defaults/upload-logo/', {
    method: 'POST',
    body: formData,
    credentials: 'include',
    headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || 'Failed to upload logo')
  }
  return response.json()
}

export async function deleteLogo(fieldName: string): Promise<CompanyDefaults> {
  const csrfToken = getCsrfToken()
  const response = await fetch('/api/company-defaults/upload-logo/', {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
    },
    body: JSON.stringify({ field_name: fieldName }),
    credentials: 'include',
  })
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || 'Failed to delete logo')
  }
  return response.json()
}
