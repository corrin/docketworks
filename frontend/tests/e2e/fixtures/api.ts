/** Direct API reads for spec setup that has no UI dependency. */
import type { Page } from '@playwright/test'
import { z } from 'zod'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export async function getCompanyDefaults(page: Page): Promise<Record<string, unknown>> {
  const response = await page.request.get('/api/company-defaults/', {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok()) {
    throw new Error(`Company defaults read failed: ${response.status()} ${await response.text()}`)
  }
  const payload: unknown = await response.json()
  if (!isRecord(payload)) {
    throw new Error(`Company defaults response was not an object: ${JSON.stringify(payload)}`)
  }
  return payload
}

const jobLabourRateSchema = z.object({
  id: z.string(),
  labour_subtype: z.string(),
  labour_subtype_name: z.string(),
  charge_out_rate: z.string(),
  is_workshop: z.boolean(),
})
export type JobLabourRate = z.infer<typeof jobLabourRateSchema>

export async function getJobLabourRates(page: Page, jobId: string): Promise<JobLabourRate[]> {
  const response = await page.request.get(`/api/job/jobs/${jobId}/labour-rates/`)
  if (!response.ok()) {
    throw new Error(`Job labour rates read failed: ${response.status()} ${await response.text()}`)
  }
  return z.array(jobLabourRateSchema).parse(await response.json())
}

const authenticatedProfileSchema = z.object({
  id: z.string(),
  email: z.string(),
  is_office_staff: z.boolean(),
  is_superuser: z.boolean(),
})
export type AuthenticatedProfile = z.infer<typeof authenticatedProfileSchema>

/** The authenticated E2E user's profile — the one staff row every spec can rely on. */
export async function getMe(page: Page): Promise<AuthenticatedProfile> {
  const response = await page.request.get('/api/accounts/me/')
  if (!response.ok()) {
    throw new Error(`Profile read failed: ${response.status()} ${await response.text()}`)
  }
  return authenticatedProfileSchema.parse(await response.json())
}
