import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'
import { getLatestWeekdayDate } from './support'

/**
 * The weekly overview and its payroll controls.
 *
 * Authored, not ported: v1 has no spec for this screen. It asserts the two
 * things the screen exists for — seeing where the week's time went, and
 * getting it into Xero — plus the drill-downs that make it the same question
 * as the daily overview at a different zoom.
 *
 * Posting itself is asserted against the pay-run state machine rather than by
 * driving a real post: a post writes to the Xero demo tenant's payroll and
 * creates a draft pay run that Xero allows only one of, so a spec that posted
 * on every run would leave the tenant in a state the next run cannot post
 * from. The button's enablement rules are what this spec pins; the posting
 * path itself is covered by the backend suite and exercised manually against
 * the demo company.
 */

/** The Monday of the week containing the given date, in local terms. */
function mondayOf(isoDate: string): string {
  const parts = isoDate.split('-')
  if (parts.length !== 3) throw new Error(`Not a YYYY-MM-DD date: ${isoDate}`)
  const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
  const weekday = date.getDay()
  date.setDate(date.getDate() - weekday + (weekday === 0 ? -6 : 1))
  const paddedMonth = String(date.getMonth() + 1).padStart(2, '0')
  const paddedDay = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${paddedMonth}-${paddedDay}`
}

async function openWeek(page: Page, week: string): Promise<void> {
  await page.goto(`/timesheets/weekly?week=${week}`)
  await page.waitForLoadState('networkidle')
  await autoId(page, 'WeeklyOverview-table').waitFor({ timeout: 30000 })
}

test.describe('weekly timesheets', () => {
  const week = mondayOf(getLatestWeekdayDate())

  test('shows the week for every staff member, with server totals', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    const rows = page.locator('[data-automation-id^="WeeklyOverview-row-"]')
    expect(await rows.count()).toBeGreaterThan(0)

    // The footer total comes from the server's weekly_summary; v1 shipped a
    // client-side recomputation alongside it and showed the client's.
    await expect(autoId(page, 'WeeklyOverview-totalHours')).toContainText('h')
  })

  test('a day header drills into that day, and a cell into that staff member’s entries', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    const firstHeader = page.locator('[data-automation-id^="WeeklyOverview-dayHeader-"]').first()
    const headerId = await firstHeader.getAttribute('data-automation-id')
    const day = headerId!.replace('WeeklyOverview-dayHeader-', '')
    await firstHeader.click()
    await page.waitForURL(`**/timesheets/daily**date=${day}**`)

    await openWeek(page, week)
    const firstCell = page.locator('[data-automation-id^="WeeklyOverview-cell-"]').first()
    await firstCell.click()
    await page.waitForURL('**/timesheets/entry**')
  })

  test('a staff row expands into its payroll categories', async ({ authenticatedPage: page }) => {
    await openWeek(page, week)

    const toggle = page.locator('[data-automation-id^="WeeklyOverview-expand-"]').first()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  })

  test('the payroll panel states the week’s pay-run position', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    // Words, never an icon alone — the operator has to be able to read this
    // without decoding a colour.
    await expect(autoId(page, 'PayrollPanel-status')).toHaveText(
      /Pay run (ready for posting|locked \(already paid\)|not created yet)/,
    )
  })

  test('posting is refused until a draft pay run exists for the week', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)

    const status = await autoId(page, 'PayrollPanel-status').textContent()
    const postButton = autoId(page, 'PayrollPanel-postAll')

    if (status?.includes('ready for posting')) {
      await expect(postButton).toBeEnabled()
    } else {
      // No run, or a locked one: either way the hours cannot go anywhere yet.
      await expect(postButton).toBeDisabled()
    }
  })

  test('a far-past week offers no pay-run creation and says why', async ({
    authenticatedPage: page,
  }) => {
    // Xero processes pay runs in sequence, so a week well before the postable
    // one must not offer to create a run out of order.
    const longAgo = mondayOf('2025-01-06')
    await openWeek(page, longAgo)

    await expect(autoId(page, 'PayrollPanel-notPostable')).toBeVisible()
    await expect(autoId(page, 'PayrollPanel-createPayRun')).toHaveCount(0)
    await expect(autoId(page, 'PayrollPanel-postAll')).toBeDisabled()
  })

  test('week navigation moves the grid and the payroll panel together', async ({
    authenticatedPage: page,
  }) => {
    await openWeek(page, week)
    const firstRange = await autoId(page, 'WeeklyOverview-range').textContent()

    await page.getByRole('button', { name: 'Previous week' }).click()
    await autoId(page, 'WeeklyOverview-table').waitFor({ timeout: 30000 })

    await expect(autoId(page, 'WeeklyOverview-range')).not.toHaveText(firstRange!)
    await expect(autoId(page, 'PayrollPanel-status')).toBeVisible()
  })
})
