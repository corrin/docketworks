import { createHash, randomBytes } from 'crypto'
import fs from 'fs'
import path from 'path'
import type { Response } from '@playwright/test'
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

    const [uploadResponse] = await Promise.all([
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

    const uploadPayload = await uploadResponse.json()
    const uploadedFileId: string | undefined = uploadPayload?.uploaded?.[0]?.id
    if (!uploadedFileId) {
      throw new Error(`Upload response missing uploaded[0].id: ${JSON.stringify(uploadPayload)}`)
    }

    await expect(page.getByText(fileName, { exact: true })).toBeVisible({ timeout: 20000 })
    await expect(autoId(page, `JobAttachmentsTab-file-row-${uploadedFileId}`)).toBeVisible({
      timeout: 10000,
    })

    page.once('dialog', (dialog) => dialog.accept())
    await autoId(page, `JobAttachmentsTab-delete-${uploadedFileId}`).click()

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

    // Pin the wait to this specific file id so concurrent list refreshes or
    // thumbnails on other files can't satisfy the matcher.
    const downloadUrlRe = new RegExp(`/api/job/jobs/${jobId}/files/${uploadedFileId}/$`)
    const [downloadResponse] = await Promise.all([
      page.waitForResponse(
        (response) => downloadUrlRe.test(response.url()) && response.request().method() === 'GET',
      ),
      autoId(page, `JobAttachmentsTab-download-${uploadedFileId}`).click(),
    ])

    expect(downloadResponse.status()).toBe(200)

    const downloadedBytes = await downloadResponse.body()
    expect(sha256(downloadedBytes)).toBe(originalSha)

    // Shared edit job is reused across tests; delete so subsequent runs start
    // from a clean attachment list.
    page.once('dialog', (dialog) => dialog.accept())
    await autoId(page, `JobAttachmentsTab-delete-${uploadedFileId}`).click()
    await expect(page.getByText(fileName, { exact: true })).toHaveCount(0)
    fs.unlinkSync(tmpPath)
  })

  test('20MB attachment shows upload progress and appears without refresh', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-attachments').click()
    await expect(page.getByText('Job Attachments')).toBeVisible({ timeout: 10000 })

    const timestamp = Date.now()
    const fileName = `large-upload-${timestamp}.txt`
    const tmpDir = path.join(process.cwd(), 'test-results', 'tmp-uploads')
    fs.mkdirSync(tmpDir, { recursive: true })
    const tmpPath = path.join(tmpDir, fileName)
    fs.writeFileSync(tmpPath, Buffer.alloc(20 * 1024 * 1024, 7))

    const fileInput = autoId(page, 'JobAttachmentsTab-file-input')
    await fileInput.waitFor({ state: 'attached' })

    const cdpSession = await page.context().newCDPSession(page)
    await cdpSession.send('Network.enable')
    await cdpSession.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: 0,
      downloadThroughput: -1,
      uploadThroughput: 5 * 1024 * 1024,
      connectionType: 'ethernet',
    })

    const startedAt = Date.now()
    const uploadResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/job/jobs/${jobId}/files/`) &&
        response.request().method() === 'POST',
      { timeout: 30000 },
    )

    let uploadResponse: Response | undefined
    try {
      await fileInput.setInputFiles(tmpPath)

      const pendingRow = page
        .locator('div', { has: page.getByText(fileName, { exact: true }) })
        .first()
      await expect(pendingRow).toBeVisible({ timeout: 5000 })
      await expect(pendingRow.getByText(/Uploading|Saving/)).toBeVisible({ timeout: 5000 })

      uploadResponse = await uploadResponsePromise
      expect(Date.now() - startedAt).toBeLessThan(30000)
      expect(uploadResponse.status()).toBeGreaterThanOrEqual(200)
      expect(uploadResponse.status()).toBeLessThan(300)
    } finally {
      await cdpSession
        .send('Network.emulateNetworkConditions', {
          offline: false,
          latency: 0,
          downloadThroughput: -1,
          uploadThroughput: -1,
          connectionType: 'ethernet',
        })
        .catch(() => undefined)
      await cdpSession.detach().catch(() => undefined)
    }

    if (!uploadResponse) {
      throw new Error('Upload did not produce a response')
    }
    const uploadPayload = await uploadResponse.json()
    const uploadedFileId: string | undefined = uploadPayload?.uploaded?.[0]?.id
    if (!uploadedFileId) {
      throw new Error(`Upload response missing uploaded[0].id: ${JSON.stringify(uploadPayload)}`)
    }

    await expect(page.getByText(fileName, { exact: true })).toBeVisible({ timeout: 10000 })
    const savedRow = autoId(page, `JobAttachmentsTab-file-row-${uploadedFileId}`)
    await expect(savedRow).toBeVisible({ timeout: 10000 })
    await expect(savedRow.getByText(/Uploading|Saving/)).toHaveCount(0)

    page.once('dialog', (dialog) => dialog.accept())
    await autoId(page, `JobAttachmentsTab-delete-${uploadedFileId}`).click()
    await expect(page.getByText(fileName, { exact: true })).toHaveCount(0)
    fs.unlinkSync(tmpPath)
  })
})
