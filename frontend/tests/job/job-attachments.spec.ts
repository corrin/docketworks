import { createHash, randomBytes } from 'crypto'
import fs from 'fs'
import path from 'path'
import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const sha256 = (buf: Buffer): string => createHash('sha256').update(buf).digest('hex')

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
          response.url().includes(`/api/job/jobs/${jobId}/files/`) &&
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

  test('uploaded attachment downloads with identical sha256', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    // JobAttachmentsTab's downloadFile() opens the blob in a new tab and calls
    // window.print(). Neutralise both so Playwright doesn't stall on the popup
    // or the native print dialog.
    await page.addInitScript(() => {
      window.print = () => undefined
    })
    page.on('popup', (popup) => {
      void popup.close().catch(() => undefined)
    })

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-attachments').click()
    await expect(page.getByText('Job Attachments')).toBeVisible({ timeout: 10000 })

    // Random payload keyed by timestamp: the filename is unique across test
    // runs and the bytes are unguessable, so a stub / cache hit can't pass.
    const timestamp = Date.now()
    const fileName = `roundtrip-${timestamp}.bin`
    const originalBytes = randomBytes(4096)
    const originalSha = sha256(originalBytes)

    const tmpDir = path.join(process.cwd(), 'test-results', 'tmp-uploads')
    fs.mkdirSync(tmpDir, { recursive: true })
    const tmpPath = path.join(tmpDir, fileName)
    fs.writeFileSync(tmpPath, originalBytes)

    const fileInput = autoId(page, 'JobAttachmentsTab-file-input')
    await fileInput.waitFor({ state: 'attached' })

    const [uploadResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes(`/api/job/jobs/${jobId}/files/`) &&
          response.request().method() === 'POST' &&
          response.status() >= 200 &&
          response.status() < 300,
      ),
      fileInput.setInputFiles(tmpPath),
    ])

    const uploadPayload = await uploadResponse.json()
    const uploadedFileId: string | undefined = uploadPayload?.uploaded?.[0]?.id
    if (!uploadedFileId) {
      throw new Error(`Upload response missing uploaded[0].id: ${JSON.stringify(uploadPayload)}`)
    }

    await expect(page.getByText(fileName, { exact: true })).toBeVisible({ timeout: 20000 })

    const fileRow = page.locator('div', { has: page.getByText(fileName, { exact: true }) }).first()

    // Pin the wait to this specific file id so concurrent list refreshes or
    // thumbnails on other files can't satisfy the matcher.
    const downloadUrlRe = new RegExp(`/api/job/jobs/${jobId}/files/${uploadedFileId}/$`)
    const [downloadResponse] = await Promise.all([
      page.waitForResponse(
        (response) => downloadUrlRe.test(response.url()) && response.request().method() === 'GET',
      ),
      fileRow.getByRole('button', { name: 'Download' }).click(),
    ])

    expect(downloadResponse.status()).toBe(200)

    const downloadedBytes = await downloadResponse.body()
    expect(sha256(downloadedBytes)).toBe(originalSha)

    // Shared edit job is reused across tests; delete so subsequent runs start
    // from a clean attachment list.
    page.once('dialog', (dialog) => dialog.accept())
    await fileRow.getByRole('button', { name: 'Delete' }).click()
    await expect(page.getByText(fileName, { exact: true })).toHaveCount(0)
    fs.unlinkSync(tmpPath)
  })
})
