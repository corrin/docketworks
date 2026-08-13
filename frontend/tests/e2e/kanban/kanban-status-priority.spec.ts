import type { Page } from '@playwright/test'

import { expect, test } from '../fixtures/auth'
import { autoId, getJobIdFromUrl } from '../helpers'

const waitForHeaderSave = (page: Page, jobId: string) =>
  page.waitForResponse(
    (response) => {
      const url = response.url()
      const method = response.request().method()
      const status = response.status()

      return (
        (url.includes(`/api/job/jobs/${jobId}/`) &&
          method === 'PATCH' &&
          status >= 200 &&
          status < 300) ||
        (url.includes(`/api/job/jobs/${jobId}/update-status/`) &&
          method === 'POST' &&
          status >= 200 &&
          status < 300)
      )
    },
    { timeout: 20000 },
  )

test.describe('kanban status priority', () => {
  test.setTimeout(120000)

  test('job appears at top of column after status change via edit view', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    // Navigate to job edit view and change status
    await page.goto(sharedEditJobUrl)
    // Unlike the kanban board, the job page opens no SSE connection, so
    // networkidle would settle here — but the status-display wait below is
    // already the deterministic ready signal, so it is redundant either way.
    const statusDisplay = autoId(page, 'JobView-status-display')
    await statusDisplay.waitFor({ timeout: 10000 })
    const currentStatusText = (await statusDisplay.textContent()) || ''

    // Pick a target status different from current
    const targetStatus = currentStatusText.includes('In Progress') ? 'draft' : 'in_progress'

    await test.step('change status via header dropdown', async () => {
      await statusDisplay.click()
      const statusSelect = autoId(page, 'JobView-status-select')
      await statusSelect.waitFor({ timeout: 5000 })
      await statusSelect.selectOption(targetStatus)
      await autoId(page, 'JobView-status-confirm').click()
      await waitForHeaderSave(page, jobId)
    })

    await test.step('verify job is at top of new kanban column', async () => {
      await page.goto('/kanban')
      // The board holds a live SSE connection, so networkidle never fires
      // here by design; wait for the board itself to render instead.
      await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

      const targetColumn = page.locator(`[data-kanban-status="${targetStatus}"]:visible`)
      await expect(targetColumn).toBeVisible({ timeout: 15000 })

      // The first job card in the column should be our job
      const firstCardInColumn = targetColumn.locator('[data-job-id]').first()
      await expect(firstCardInColumn).toBeVisible({ timeout: 15000 })
      await expect(firstCardInColumn).toHaveAttribute('data-job-id', jobId)
    })
  })
})
