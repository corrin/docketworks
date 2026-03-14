import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

const waitForHeaderSave = (page: Page, jobId: string) =>
  page.waitForResponse(
    (response) => {
      const url = response.url()
      const method = response.request().method()
      const status = response.status()

      if (
        url.includes(`/job/rest/jobs/${jobId}/`) &&
        method === 'PATCH' &&
        status >= 200 &&
        status < 300
      ) {
        return true
      }

      if (
        url.includes(`/job/api/jobs/${jobId}/update-status/`) &&
        method === 'POST' &&
        status >= 200 &&
        status < 300
      ) {
        return true
      }

      return false
    },
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
