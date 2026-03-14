import path from 'path'
import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

test.describe('job attachments', () => {
  test.setTimeout(120000)

  test('upload and delete job attachments', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-attachments').click()
    await expect(page.getByText('Job Attachments')).toBeVisible({ timeout: 10000 })

    const fixturePath = path.join(
      process.cwd(),
      'tests',
      'fixtures',
      'files',
      'sample-attachment.txt',
    )
    const fileName = 'sample-attachment.txt'

    const fileInput = autoId(page, 'JobAttachmentsTab-file-input')
    await fileInput.waitFor({ state: 'attached' })

    await Promise.all([
      page.waitForResponse((response) => {
        return (
          response.url().includes(`/job/rest/jobs/${jobId}/files/`) &&
          response.request().method() === 'POST' &&
          response.status() >= 200 &&
          response.status() < 300
        )
      }),
      fileInput.setInputFiles(fixturePath),
    ])

    await expect(page.getByText(fileName, { exact: true })).toBeVisible({ timeout: 20000 })

    const fileRow = page.locator('div', { has: page.getByText(fileName, { exact: true }) }).first()

    page.once('dialog', (dialog) => dialog.accept())
    await fileRow.getByRole('button', { name: 'Delete' }).click()

    await expect(page.getByText(fileName, { exact: true })).toHaveCount(0)
  })
})
