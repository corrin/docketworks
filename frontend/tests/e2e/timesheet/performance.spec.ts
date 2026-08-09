import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { getLatestWeekdayDate } from './support'

/**
 * Observational performance probes for the entry page. The hard failure
 * modes are the 60s grid/spinner waits (and the auth fixture's wire-size
 * cap); the 5s load figure and the sequential-request check log warnings
 * rather than failing, exactly as in v1.
 */

async function firstStaffId(page: Page, date: string): Promise<string> {
  await page.goto(`/timesheets/daily?date=${date}`)
  const firstStaff = page.locator('[data-automation-id^="StaffRow-name-"]').first()
  await firstStaff.waitFor({ timeout: 10000 })
  const automationId = await firstStaff.getAttribute('data-automation-id')
  const staffId = automationId?.replace('StaffRow-name-', '')
  if (!staffId) throw new Error(`Could not derive staffId from ${automationId}`)
  return staffId
}

test.describe('timesheet entry performance', () => {
  test('measure page load time and network requests', async ({ authenticatedPage: page }) => {
    const date = getLatestWeekdayDate()
    const staffId = await firstStaffId(page, date)

    const requests: { url: string; start: number; end?: number }[] = []
    const t0 = Date.now()
    page.on('request', (request) => {
      const url = request.url()
      if (url.includes('/api/') || url.includes('/job/') || url.includes('/timesheets/')) {
        requests.push({ url: url.replace(/.*\/\/[^/]+/, ''), start: Date.now() - t0 })
      }
    })
    page.on('response', (response) => {
      const url = response.url().replace(/.*\/\/[^/]+/, '')
      const entry = requests.findLast((candidate) => candidate.url === url && !candidate.end)
      if (entry) entry.end = Date.now() - t0
    })

    const navStart = Date.now()
    await page.goto(`/timesheets/entry?date=${date}&staffId=${staffId}`)
    const grid = page.locator('.smart-timesheet-table')
    await grid.waitFor({ state: 'visible', timeout: 60000 })
    await page.waitForFunction(() => !document.querySelector('.animate-spin'), { timeout: 60000 })
    const totalLoadTime = Date.now() - navStart

    console.log(`Entry page loaded in ${totalLoadTime}ms with ${requests.length} API calls`)
    const byPath = new Map<string, number>()
    for (const request of requests) {
      const path = request.url.split('?')[0] ?? request.url
      byPath.set(path, (byPath.get(path) ?? 0) + 1)
    }
    for (const [path, count] of byPath) {
      if (count > 1) console.log(`Duplicate request: ${path} × ${count}`)
    }
    if (totalLoadTime > 5000) {
      console.log(`WARNING: Page load time (${totalLoadTime}ms) exceeds 5 seconds!`)
    }
    await expect(grid).toBeVisible()
  })

  test('measure sequential vs parallel API behavior', async ({ authenticatedPage: page }) => {
    const date = getLatestWeekdayDate()
    const staffId = await firstStaffId(page, date)

    const timings: { url: string; start: number; end: number }[] = []
    const t0 = Date.now()
    page.on('response', (response) => {
      const url = response.url()
      if (url.includes('/api/') || url.includes('/timesheets/')) {
        const request = response.request()
        const timing = request.timing()
        timings.push({
          url: url.replace(/.*\/\/[^/]+/, ''),
          start: timing.startTime > 0 ? timing.startTime - t0 : Date.now() - t0,
          end: Date.now() - t0,
        })
      }
    })

    await page.goto(`/timesheets/entry?date=${date}&staffId=${staffId}`)
    await page.locator('.smart-timesheet-table').waitFor({ state: 'visible', timeout: 60000 })

    if (timings.length === 0) {
      console.log('No API requests captured')
      return
    }
    timings.sort((a, b) => a.start - b.start)
    let sequentialCount = 0
    let parallelCount = 0
    for (let i = 1; i < timings.length; i++) {
      if (timings[i]!.start >= timings[i - 1]!.end) sequentialCount++
      else parallelCount++
    }
    console.log(`Sequential: ${sequentialCount}, parallel: ${parallelCount}`)
    if (sequentialCount > parallelCount * 2) {
      console.log('WARNING: Requests appear to be mostly sequential - could be parallelized!')
    }
    await expect(page.locator('.smart-timesheet-table')).toBeVisible()
  })
})
