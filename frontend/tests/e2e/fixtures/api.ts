/** Direct API reads for spec setup that has no UI dependency. */
import type { Page } from '@playwright/test'

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
