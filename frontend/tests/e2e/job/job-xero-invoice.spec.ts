import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'
import { runManagePy } from '../../scripts/db-backup-utils'
import { zXeroCreateInvoiceResponse } from '../../../src/api/generated/zod.gen'

test.describe('job xero invoice', () => {
  test.setTimeout(120000)

  test('invoice a job from Finish Job and see the balance settle', async ({
    authenticatedPage: page,
  }) => {
    // A dedicated job, not sharedEditJobUrl: this spec fully invoices the job
    // and flips fully_invoiced, and the shared fixture is read-only by
    // contract (v1 mutated the shared job and survived on run ordering).
    const jobUrl = await createTestJob(page, 'Invoice', {
      materials: '1000',
      time: '8',
      pricing: 'fixed_price',
    })
    const jobId = getJobIdFromUrl(jobUrl)

    await page.goto(jobUrl)
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

    // KAN-381: Docketworks raises the invoice as a draft, and a draft deletes
    // outright (an approved one would be offered a void instead).
    const deleteResponse = page.waitForResponse(
      (candidate) =>
        candidate.url().includes(`/api/xero/delete_invoice/${jobId}`) &&
        candidate.request().method() === 'DELETE',
    )
    await invoiceItems.first().locator('[data-automation-id^="JobInvoiceCard-delete-"]').click()
    expect((await deleteResponse).ok()).toBe(true)

    await expect(invoiceItems).toHaveCount(initialCount, { timeout: 20000 })
    await expect(remaining).not.toHaveText(/\$0\.00/, { timeout: 20000 })
    await expect(createInvoiceButton).toBeVisible()
  })

  test('an invoice approved in Xero is offered a void, not deleted', async ({
    authenticatedPage: page,
  }) => {
    // KAN-381: deleting an approved invoice sent a delete Xero refuses. Now the
    // user is offered a void (or a second invoice) and Xero sees only the void.
    const jobUrl = await createTestJob(page, 'Invoice void', {
      materials: '1000',
      time: '8',
      pricing: 'fixed_price',
    })
    const jobId = getJobIdFromUrl(jobUrl)

    await page.goto(jobUrl)
    await page.waitForLoadState('networkidle')
    await autoId(page, 'JobViewTabs-finishJob').click()
    const remaining = autoId(page, 'JobFinishTab-remaining-excl-gst')
    await expect(remaining).not.toHaveText(/\$0\.00/, { timeout: 10000 })

    const created = page.waitForResponse(
      (candidate) =>
        candidate.url().includes(`/api/xero/create_invoice/${jobId}`) &&
        candidate.request().method() === 'POST',
      { timeout: 120000 },
    )
    await autoId(page, 'JobFinishTab-create-invoice').click()
    await autoId(page, 'JobFinishTab-mode-invoice-full').click()
    const createdResponse = await created
    expect(createdResponse.ok()).toBe(true)
    const { xero_id: xeroId } = zXeroCreateInvoiceResponse.parse(await createdResponse.json())

    // What office staff do in Xero's own screen, and the webhook brings back.
    runManagePy(['approve_xero_invoice', xeroId])
    await page.reload()
    await page.waitForLoadState('networkidle')
    await autoId(page, 'JobViewTabs-finishJob').click()

    const invoiceRow = autoId(page, 'JobInvoiceCard-list').locator('li').first()
    await expect(invoiceRow).toContainText('Awaiting Payment', { timeout: 20000 })
    await expect(remaining).toHaveText(/\$0\.00/)

    await invoiceRow.locator('[data-automation-id^="JobInvoiceCard-delete-"]').click()
    const offer = autoId(page, 'JobInvoiceCard-void-offer')
    await expect(offer).toContainText('is already approved so cannot be simply deleted')

    const voided = page.waitForResponse(
      (candidate) =>
        candidate.url().includes(`/api/xero/delete_invoice/${jobId}`) &&
        candidate.url().includes('void_approved=true'),
    )
    await autoId(page, 'JobInvoiceCard-void-offer-void').click()
    expect((await voided).ok()).toBe(true)

    // The voided invoice stays on the job, can't be deleted, and no longer counts.
    await expect(invoiceRow).toContainText('Voided', { timeout: 20000 })
    await expect(
      invoiceRow.locator('[data-automation-id^="JobInvoiceCard-delete-"]'),
    ).toBeDisabled()
    await expect(remaining).not.toHaveText(/\$0\.00/, { timeout: 20000 })
  })
})
