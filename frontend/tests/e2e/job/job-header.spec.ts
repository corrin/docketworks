import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId, getJobIdFromUrl } from '../helpers'

// Both header edits (name and status) ride the delta PATCH; v1 also accepted
// the kanban update-status POST here, but nothing in this app calls it.
const waitForHeaderSave = (page: Page, jobId: string) =>
  page.waitForResponse(
    (response) =>
      response.url().includes(`/api/job/jobs/${jobId}/`) &&
      response.request().method() === 'PATCH' &&
      response.status() >= 200 &&
      response.status() < 300,
    { timeout: 20000 },
  )

test.describe('job header', () => {
  test.setTimeout(120000)

  test('update job name and status from header', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobView-job-number').waitFor({ timeout: 10000 })
    const headerRow = autoId(page, 'JobView-job-number').locator('..')
    const nameEditor = headerRow.locator('.inline-edit-text')
    await expect(nameEditor).toBeVisible({ timeout: 10000 })

    const newJobName = `Header Update ${Date.now()}`

    await nameEditor.click()
    const nameInput = nameEditor.locator('input')
    await nameInput.fill(newJobName)
    await nameInput.press('Enter')

    await waitForHeaderSave(page, jobId)

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(nameEditor).toContainText(newJobName)

    const statusDisplay = autoId(page, 'JobView-status-display')
    const currentStatusText = (await statusDisplay.textContent()) || ''
    const targetStatus = currentStatusText.includes('In Progress') ? 'draft' : 'in_progress'
    const targetLabel = targetStatus === 'draft' ? 'Draft' : 'In Progress'

    await statusDisplay.click()
    const statusSelect = autoId(page, 'JobView-status-select')
    await statusSelect.selectOption(targetStatus)
    await autoId(page, 'JobView-status-confirm').click()

    await waitForHeaderSave(page, jobId)

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(statusDisplay).toContainText(targetLabel)
  })
})
