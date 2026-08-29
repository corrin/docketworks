import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob } from '../helpers'
import { readJobNumber } from './support'

/**
 * The workshop "my time" calendar: day navigation, refresh, and the
 * add/update/delete round trip through the entry drawer.
 *
 * Port deviations from v1, each deliberate:
 * - The shared job is created by the first serial test through the standard
 *   authenticated fixture, not a hand-rolled beforeAll login.
 * - The job picker is the shared JobPicker popover, not v1's separate
 *   picker drawer, so selection goes trigger → search → option.
 * - There is no hours field: the drawer derives hours from the start/end
 *   pair (the server refuses a trio that disagrees).
 * - The calendar block must carry the id the create response returned —
 *   v1 only console.warned on a mismatch.
 */

const CALENDAR_EVENT = (entryId: string) =>
  `[data-automation-id="WorkshopTimesheetCalendar"] [data-event-id="${entryId}"]`

async function openMyTimeView(page: Page): Promise<void> {
  await page.goto('/timesheets/my-time')
  await expect(page.getByText('Workshop timesheets')).toBeVisible({ timeout: 15000 })
  await autoId(page, 'WorkshopMyTimeHeader-date').waitFor({ timeout: 10000 })
}

function timesheetResponse(page: Page, method: 'GET' | 'POST' | 'PATCH' | 'DELETE') {
  return page.waitForResponse(
    (response) =>
      response.url().includes('/api/job/workshop/timesheets/') &&
      response.request().method() === method &&
      [200, 201, 204].includes(response.status()),
    { timeout: 15000 },
  )
}

async function selectJobInPicker(page: Page, jobNumber: number): Promise<void> {
  await autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker-trigger').click()
  const search = autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker-search')
  await expect(search).toBeVisible({ timeout: 10000 })
  await search.fill(String(jobNumber))
  const option = autoId(page, `WorkshopTimesheetEntryDrawer-job-picker-option-${jobNumber}`)
  await option.waitFor({ timeout: 10000 })
  await option.click()
}

test.describe.serial('workshop my time view', () => {
  let jobNumber = 0

  test('create the shared job', async ({ authenticatedPage: page }) => {
    await createTestJob(page, 'Workshop My Time')
    jobNumber = await readJobNumber(page)
  })

  test('moves between days', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)
    const dateBadge = autoId(page, 'WorkshopMyTimeHeader-date')
    const initialDate = (await dateBadge.textContent())?.trim() ?? ''
    expect(initialDate).not.toBe('')

    await test.step('move to previous day', async () => {
      await autoId(page, 'WorkshopMyTimeHeader-previous-day').click()
      await expect(dateBadge).not.toHaveText(initialDate)
    })

    await test.step('move to next day', async () => {
      await autoId(page, 'WorkshopMyTimeHeader-next-day').click()
      await expect(dateBadge).toHaveText(initialDate)
    })
  })

  test('refreshes a day', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)

    const refresh = timesheetResponse(page, 'GET')
    await autoId(page, 'WorkshopTimesheetSummaryCard-refresh').click()
    await refresh
  })

  test('adds, updates, and deletes an entry', async ({ authenticatedPage: page }) => {
    await openMyTimeView(page)
    let entryId = ''

    await test.step('add a new entry via the drawer', async () => {
      await autoId(page, 'WorkshopTimesheetSummaryCard-add').click()
      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeVisible({
        timeout: 10000,
      })

      await selectJobInPicker(page, jobNumber)
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-job-picker-trigger')).toContainText(
        `#${jobNumber}`,
      )

      await autoId(page, 'WorkshopTimesheetEntryDrawer-start-time').fill('08:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('09:00')
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-duration')).toContainText('1h')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-description').fill('Workshop test entry')

      const submit = autoId(page, 'WorkshopTimesheetEntryDrawer-submit')
      await expect(submit).toBeEnabled({ timeout: 10000 })
      const createResponse = timesheetResponse(page, 'POST')
      await submit.click()

      const body: unknown = await (await createResponse).json()
      if (
        typeof body !== 'object' ||
        body === null ||
        !('id' in body) ||
        typeof body.id !== 'string'
      ) {
        throw new Error('Create response carried no entry id.')
      }
      entryId = body.id

      await expect(page.getByRole('heading', { name: 'Add entry' })).toBeHidden({
        timeout: 10000,
      })
      const eventBlock = page.locator(CALENDAR_EVENT(entryId))
      await expect(eventBlock).toBeVisible({ timeout: 15000 })
      await expect(eventBlock).toContainText(`#${jobNumber}`)
    })

    await test.step('update the entry', async () => {
      await page.locator(CALENDAR_EVENT(entryId)).click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })

      await autoId(page, 'WorkshopTimesheetEntryDrawer-end-time').fill('10:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-description').fill(
        'Workshop test entry updated',
      )

      const update = timesheetResponse(page, 'PATCH')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-submit').click()
      await update
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })

      await page.locator(CALENDAR_EVENT(entryId)).click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-description')).toHaveValue(
        'Workshop test entry updated',
      )
      await expect(autoId(page, 'WorkshopTimesheetEntryDrawer-end-time')).toHaveValue('10:00')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-cancel').click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })
    })

    await test.step('delete the entry', async () => {
      await page.locator(CALENDAR_EVENT(entryId)).click()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible({
        timeout: 10000,
      })

      const destroy = timesheetResponse(page, 'DELETE')
      await autoId(page, 'WorkshopTimesheetEntryDrawer-delete').click()
      await destroy
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeHidden({
        timeout: 10000,
      })
      await expect(page.locator(CALENDAR_EVENT(entryId))).toHaveCount(0)
    })
  })
})
