/**
 * What the phone specs share: the office's part, done in a desktop Chromium
 * the spec launches itself (the phone browser only ever carries the workshop
 * user's session), and the company address every My time write is judged by.
 */
import type { BrowserType, Page } from '@playwright/test'
import { z } from 'zod'

import { getCompanyDefaults } from '../fixtures/api'
import { authenticateViaLoginPage, e2eCredentials } from '../fixtures/auth'

// A real street address Google knows.
const COMPANY_PLACE_ID = 'ChIJCTlhFsxIDW0RYNfpF_7ReVA'

export async function asOffice<T>(
  chromium: BrowserType,
  baseURL: string,
  work: (page: Page) => Promise<T>,
): Promise<T> {
  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({ baseURL, viewport: { width: 1280, height: 720 } })
    const page = await context.newPage()
    const { username, password } = e2eCredentials('office')
    await authenticateViaLoginPage(page, username, password, () => () => undefined)
    return await work(page)
  } finally {
    await browser.close()
  }
}

// The coordinates are decimal columns and travel as text.
const addressSchema = z.object({
  google_place_id: z.string().nullable(),
  latitude: z.string().nullable(),
  longitude: z.string().nullable(),
})

export interface Position {
  latitude: number
  longitude: number
}

/**
 * Run `work` with the company address set, then put back the one there was.
 * The address is picked as the settings screen picks it, by place id, and the
 * server re-reads its coordinates from Google. `work` gets a position at the
 * workshop and one well away from it.
 */
export async function withCompanyAddress<T>(
  chromium: BrowserType,
  baseURL: string,
  page: Page,
  work: (positions: { atTheWorkshop: Position; elsewhere: Position }) => Promise<T>,
): Promise<T> {
  const setCompanyAddress = (placeId: string | null) =>
    asOffice(chromium, baseURL, async (office) => {
      const response = await office.request.patch('/api/company-defaults/', {
        data: { google_place_id: placeId },
      })
      if (!response.ok()) {
        throw new Error(`Company address save answered ${response.status()}`)
      }
      return addressSchema.parse(await response.json())
    })
  const before = addressSchema.parse(await getCompanyDefaults(page))
  try {
    const address = await setCompanyAddress(COMPANY_PLACE_ID)
    if (address.latitude === null || address.longitude === null) {
      throw new Error('The picked company address came back without coordinates.')
    }
    const atTheWorkshop = {
      latitude: Number(address.latitude),
      longitude: Number(address.longitude),
    }
    // Half a degree of latitude is about 55 km.
    const elsewhere = { ...atTheWorkshop, latitude: atTheWorkshop.latitude + 0.5 }
    return await work({ atTheWorkshop, elsewhere })
  } finally {
    await setCompanyAddress(before.google_place_id)
  }
}
