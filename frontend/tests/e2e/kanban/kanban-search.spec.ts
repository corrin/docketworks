/**
 * KAN-353 — finding a job from the board: numeric search, and the Archived column.
 *
 * The existing kanban specs drive the search box with searchInput.fill(),
 * which is one atomic change event. The reported bug needs the 300ms debounce
 * to fire MID-WORD, which only pressSequentially() (a real keystroke each)
 * reproduces — that fill-vs-type gap is why every gate stayed green while the
 * main search path was broken in production.
 */
import type { Page } from '@playwright/test'

import { expect, test } from '../fixtures/auth'
import { getJobIdFromUrl } from '../helpers'
import { getVisibleJobCard } from './support'

/** Longer than SEARCH_DEBOUNCE_MS (300ms), so the debounced navigation lands. */
const PAST_DEBOUNCE_MS = 600

const openBoard = async (page: Page): Promise<void> => {
  await page.goto('/kanban')
  // The board holds a live SSE connection, so networkidle never fires here by
  // design; wait for the board itself to render instead.
  await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()
}

/** The card's `#1234` badge, per JobCard's DOM contract (its first span). */
const readJobNumber = async (page: Page, jobId: string): Promise<string> => {
  const card = getVisibleJobCard(page, jobId)
  await expect(card).toBeVisible({ timeout: 15000 })
  const badge = (await card.locator('span').first().textContent())?.trim() ?? ''
  const jobNumber = badge.replace(/^#/, '')
  // Fail loudly rather than typing an empty term and asserting on nothing.
  expect(jobNumber, `expected a #job_number badge on card ${jobId}, saw ${badge}`).toMatch(/^\d+$/)
  return jobNumber
}

test.describe.serial('kanban search', () => {
  test('typing a job number searches for that number', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)
    await openBoard(page)
    const jobNumber = await readJobNumber(page, jobId)

    const searchInput = page.getByPlaceholder('Search jobs...')
    await searchInput.click()

    // One character, then a pause past the debounce: this is the exact
    // sequence that corrupted the box. The remaining characters follow.
    await searchInput.pressSequentially(jobNumber.slice(0, 1))
    await page.waitForTimeout(PAST_DEBOUNCE_MS)
    await searchInput.pressSequentially(jobNumber.slice(1))
    await page.waitForTimeout(PAST_DEBOUNCE_MS)

    // The box holds what was typed — not `"9"7537`.
    await expect(searchInput).toHaveValue(jobNumber)
    // The search found the job whose number was typed.
    await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })
  })

  test('a shared unquoted ?q= link filters the board', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)
    await openBoard(page)
    const jobNumber = await readJobNumber(page, jobId)

    // How a person writes the link by hand. It parses to a NUMBER, which the
    // route used to drop — leaving an unfiltered board under a filled-in box.
    await page.goto(`/kanban?q=${jobNumber}`)
    await expect(page.getByPlaceholder('Search jobs...')).toHaveValue(jobNumber)
    await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })
  })

  test('the board renders an Archived column', async ({ authenticatedPage: page }) => {
    await openBoard(page)

    // Archived is where ~95% of the jobs live; without a column, an old job
    // was unreachable by eye from the board at all. The list element carries
    // data-kanban-status; its heading is a sibling in the same panel.
    const archivedList = page.locator('[data-kanban-status="archived"]:visible')
    await expect(archivedList).toHaveCount(1, { timeout: 15000 })
    await expect(page.getByRole('heading', { name: 'Archived' })).toBeVisible()
  })
})
