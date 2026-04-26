import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

test.describe('print delivery docket', () => {
  test.setTimeout(60000)

  test('GET /delivery-docket/ returns a PDF', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    // Stub window.open so the handler's blob-URL popup + win.print() native
    // dialog don't hang the test. We only need to verify the GET returns PDF
    // bytes — backend rendering is covered by apps.job.tests.test_pdf_goldens.
    await page.evaluate(() => {
      window.open = () => null
    })

    const printButton = autoId(page, 'JobView-print-delivery-docket')
    await expect(printButton).toBeVisible({ timeout: 10000 })

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/job/jobs/${jobId}/delivery-docket/`) &&
        response.request().method() === 'GET',
      { timeout: 30000 },
    )

    await printButton.click()
    const response = await responsePromise

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('application/pdf')
    // Django streams the PDF chunked, so Content-Length is absent — measure
    // the body directly. Backend rendering is covered by
    // apps.job.tests.test_pdf_goldens; here we just confirm the wire actually
    // carries PDF bytes.
    const body = await response.body()
    expect(body.length).toBeGreaterThan(1000)
    expect(body.slice(0, 4).toString()).toBe('%PDF')
  })
})
