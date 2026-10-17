import type { Page } from '@playwright/test'

import { test, expect } from '../fixtures/auth'
import {
  addAdjustmentCostLine,
  autoId,
  createTestJob,
  getJobIdFromUrl,
  openJobCostingTab,
} from '../helpers'
import { getVisibleJobCard } from '../kanban/support'

const jobMutation = (page: Page, jobId: string, suffix = '', method = 'PATCH') =>
  page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/job/jobs/${jobId}/${suffix}` &&
      response.request().method() === method,
  )

test.describe('job rejection', () => {
  test.use({ loginRole: 'officeStaff' })
  test('a zero-value job is rejected, undone, and reopened with persistent history and board state', async ({
    authenticatedPage: page,
  }) => {
    const url = await createTestJob(page, 'Rejection')
    const jobId = getJobIdFromUrl(url)
    const jobNumber = (await autoId(page, 'JobView-job-number').innerText()).match(/\d+/)?.[0]
    expect(jobNumber).toBeTruthy()
    await autoId(page, 'JobView-status-display').click()
    await autoId(page, 'JobView-status-select').selectOption('in_progress')
    const statusSaved = jobMutation(page, jobId)
    await autoId(page, 'JobView-status-confirm').click()
    const statusResponse = await statusSaved
    expect(statusResponse.status(), await statusResponse.text()).toBe(200)
    await expect(autoId(page, 'JobView-status-display')).toHaveText('In Progress')

    const rejected = jobMutation(page, jobId)
    await autoId(page, 'JobView-rejection-action').click()
    const rejectedResponse = await rejected
    expect(rejectedResponse.status(), await rejectedResponse.text()).toBe(200)
    await expect(autoId(page, 'JobView-rejected-badge')).toBeVisible()
    await expect(autoId(page, 'JobView-status-display')).toHaveText('Archived')
    await page.reload()
    await expect(autoId(page, 'JobView-rejection-action')).toHaveText('Reopen job')
    await expect(autoId(page, 'JobView-rejected-badge')).toBeVisible()

    await page.goto(`/kanban?q=${jobNumber}`)
    const card = getVisibleJobCard(page, jobId)
    await expect(
      page.locator('[data-kanban-status="archived"]').locator(`[data-job-id="${jobId}"]`),
    ).toBeVisible()
    await expect(card.getByLabel('Rejected')).toBeVisible()
    await card.click()
    await autoId(page, 'JobViewTabs-history').click()
    const rejection = autoId(page, 'JobHistoryTab-timeline')
      .locator('[data-automation-id^="JobHistoryTab-entry-"]')
      .filter({ hasText: 'Job marked as rejected' })
    await expect(rejection).toHaveCount(1)
    await rejection.locator('[data-automation-id^="JobHistoryTab-undo-toggle-"]').click()
    const undone = jobMutation(page, jobId, 'undo-change/', 'POST')
    await rejection.locator('[data-automation-id^="JobHistoryTab-undo-confirm-"]').click()
    const undoneResponse = await undone
    expect(undoneResponse.status(), await undoneResponse.text()).toBe(200)
    await expect(autoId(page, 'JobView-rejected-badge')).toHaveCount(0)
    await expect(autoId(page, 'JobView-status-display')).toHaveText('In Progress')

    const rejectedAgain = jobMutation(page, jobId)
    await autoId(page, 'JobView-rejection-action').click()
    const secondResponse = await rejectedAgain
    expect(secondResponse.status(), await secondResponse.text()).toBe(200)
    await expect(autoId(page, 'JobView-rejection-action')).toHaveText('Reopen job')
    await autoId(page, 'JobView-rejection-action').click()
    await expect(autoId(page, 'JobView-rejection-confirm')).toHaveText('Reopen in Draft')
    await autoId(page, 'JobView-rejection-cancel').click()
    await expect(autoId(page, 'JobView-status-display')).toHaveText('Archived')
    await autoId(page, 'JobView-rejection-action').click()
    const reopened = jobMutation(page, jobId)
    await autoId(page, 'JobView-rejection-confirm').click()
    const reopenedResponse = await reopened
    expect(reopenedResponse.status(), await reopenedResponse.text()).toBe(200)
    await expect(autoId(page, 'JobView-status-display')).toHaveText('Draft')
    await expect(autoId(page, 'JobView-rejected-badge')).toHaveCount(0)
    await page.reload()
    await expect(autoId(page, 'JobView-rejection-action')).toHaveText('Reject job')
    await expect(autoId(page, 'JobView-status-display')).toHaveText('Draft')
    await page.goto(`/kanban?q=${jobNumber}`)
    await expect(
      page.locator('[data-kanban-status="draft"]').locator(`[data-job-id="${jobId}"]`),
    ).toBeVisible()
    await expect(getVisibleJobCard(page, jobId).getByLabel('Rejected')).toHaveCount(0)
  })

  test('uninvoiced value warns, supports keyboard cancellation, and stays usable across viewport sizes', async ({
    authenticatedPage: page,
  }, testInfo) => {
    const url = await createTestJob(page, 'Rejection warning', {
      jobName: `[TEST] ${'Long fabrication job name '.repeat(3)}${Date.now()}`.slice(0, 100),
    })
    const jobId = getJobIdFromUrl(url)
    await openJobCostingTab(page, url, 'actual')
    await addAdjustmentCostLine(page, 'Actual Costs', 'Cancellation work', '1', '100')
    await autoId(page, 'JobViewTabs-finishJob').click()
    const remaining = autoId(page, 'JobFinishTab-remaining-excl-gst')
    await expect(remaining).toBeVisible()
    await expect(remaining).not.toHaveText('$0.00')
    const amount = (await remaining.innerText()).trim()
    await autoId(page, 'JobView-rejection-action').focus()
    await page.keyboard.press('Enter')
    await expect(autoId(page, 'JobView-rejection-warning')).toContainText(amount)
    await expect(autoId(page, 'JobView-rejected-badge')).toHaveCount(0)
    for (const width of [1920, 1366, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await expect(autoId(page, 'JobView-rejection-confirm')).toBeInViewport()
      await expect(autoId(page, 'JobView-rejection-cancel')).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      )
      await page.screenshot({ path: testInfo.outputPath(`rejection-warning-${width}.png`) })
    }
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(autoId(page, 'JobView-rejection-action')).toBeFocused()
    await expect(autoId(page, 'JobView-rejected-badge')).toHaveCount(0)
    await autoId(page, 'JobView-rejection-action').click()
    await expect(autoId(page, 'JobView-rejection-warning')).toContainText(amount)
    const rejected = jobMutation(page, jobId)
    await autoId(page, 'JobView-rejection-confirm').click()
    const response = await rejected
    expect(response.status(), await response.text()).toBe(200)
    await expect(autoId(page, 'JobView-status-display')).toHaveText('Archived')
    await expect(autoId(page, 'JobView-rejected-badge')).toBeVisible()
    await page.reload()
    await expect(autoId(page, 'JobView-rejection-action')).toHaveText('Reopen job')
  })
})
