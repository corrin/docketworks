import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

test.describe('print workshop pdf', () => {
  test.setTimeout(60000)

  test('GET /workshop-pdf/ returns a PDF', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    const printButton = autoId(page, 'JobView-print-workshop-pdf')
    await expect(printButton).toBeVisible({ timeout: 10000 })

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/job/jobs/${jobId}/workshop-pdf/`) &&
        response.request().method() === 'GET',
      { timeout: 30000 },
    )

    await printButton.click()
    const response = await responsePromise

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('application/pdf')
    expect(Number(response.headers()['content-length'] ?? 0)).toBeGreaterThan(1000)
  })
})
