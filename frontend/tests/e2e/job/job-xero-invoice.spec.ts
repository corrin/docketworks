import { test, expect } from '../fixtures/auth'
import { autoId, getJobIdFromUrl } from '../helpers'

test.describe('job xero invoice', () => {
  test.setTimeout(120000)

  test('invoice a job from Finish Job and see the balance settle', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto(sharedEditJobUrl)
    await page.waitForLoadState('networkidle')

    await autoId(page, 'JobViewTabs-finishJob').click()

    // The balance is server-owned; the tab must render it before offering to invoice.
    await expect(autoId(page, 'JobFinishTab-total-to-pay')).toBeVisible({ timeout: 10000 })
    const remaining = autoId(page, 'JobFinishTab-remaining-excl-gst')
    await expect(remaining).toBeVisible()
    await expect(remaining).not.toHaveText(/\$0\.00/)

    const invoiceItems = autoId(page, 'JobInvoiceCard-list').locator('li')
    const initialCount = await invoiceItems.count()

    const createInvoiceButton = autoId(page, 'JobFinishTab-create-invoice')
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

    const invoiceFullButton = autoId(page, 'JobFinishTab-mode-invoice-full')
    await expect(invoiceFullButton).toBeVisible({ timeout: 10000 })
    await invoiceFullButton.click()

    const response = await responsePromise
    if (!response.ok()) {
      const body = await response.text()
      throw new Error(
        `Xero invoice create failed: ${response.status()} ${response.statusText()} ${body}`,
      )
    }

    await expect(invoiceItems).toHaveCount(initialCount + 1, { timeout: 20000 })

    // KAN-323: a fully invoiced job shows nothing remaining and stops asking for
    // another invoice, rather than offering a ceremonial $0 one.
    await expect(remaining).toHaveText(/\$0\.00/, { timeout: 20000 })
    await expect(autoId(page, 'JobFinishTab-fully-invoiced')).toBeVisible()
    await expect(createInvoiceButton).toHaveCount(0)
  })
})
