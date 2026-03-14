import { test, expect } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
  return match[1]
}

test.describe('job xero invoice', () => {
  test.setTimeout(120000)

  test('create invoice in Xero from Actual tab', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-actual').click()

    const invoiceItems = page.locator('ul[role="list"] li')
    const initialCount = await invoiceItems.count()

    const createInvoiceButton = page.getByRole('button', { name: /Create .*Invoice/ })
    await expect(createInvoiceButton).toBeVisible({ timeout: 10000 })

    const responsePromise = page.waitForResponse(
      (response) => {
        return (
          response.url().includes(`/api/xero/create_invoice/${jobId}`) &&
          response.request().method() === 'POST'
        )
      },
      { timeout: 120000 },
    )

    await createInvoiceButton.click()
    const response = await responsePromise
    if (!response.ok()) {
      const body = await response.text()
      throw new Error(
        `Xero invoice create failed: ${response.status()} ${response.statusText()} ${body}`,
      )
    }

    await expect(invoiceItems).toHaveCount(initialCount + 1, { timeout: 20000 })
  })
})
