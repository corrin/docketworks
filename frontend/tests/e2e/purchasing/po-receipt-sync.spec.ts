import type { PurchaseOrderDetail } from '../../../src/api/generated/types.gen'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder, waitForPoAutosave } from '../helpers'

// GPT: letting Xero AUTHORISED overwrite a receipt would revert both visible
// labels after this real push/pull, even though the receipt quantity survives.
test('a fully received order stays received after its real Xero push and pull', async ({
  authenticatedPage: page,
}) => {
  // GPT: the existing admin control runs the complete tenant sync, not just this PO.
  test.setTimeout(600_000)
  const poUrl = await createTestPurchaseOrder(page)
  const poId = new URL(poUrl).pathname.split('/').at(-1)
  const detailPath = `/api/purchasing/purchase-orders/${poId}/`
  await autoId(page, 'PoLinesTable-description-0').fill('[TEST] receipt sync steel sheet')
  await autoId(page, 'PoLinesTable-quantity-0').fill('1')
  await autoId(page, 'PoLinesTable-unit-cost-0').fill('100')
  const lineSaved = waitForPoAutosave(page)
  await page.keyboard.press('Tab')
  await lineSaved

  const draftResponse = await page.request.get(detailPath)
  expect(draftResponse.ok(), await draftResponse.text()).toBe(true)
  const draft: PurchaseOrderDetail = await draftResponse.json()
  expect(draft.xero_id).toBeNull()

  await autoId(page, 'PoSummaryCard-status-trigger').click()
  const receiptSaved = waitForPoAutosave(page)
  await autoId(page, 'PoSummaryCard-status-fully_received').click()
  await receiptSaved
  await expect(autoId(page, 'PoSummaryCard-status-trigger')).toHaveText('Fully Received')

  // GPT: draft edits queue no push. The first identity therefore proves the
  // received version reached Xero before the inbound sync is requested.
  await expect
    .poll(
      async () => {
        const response = await page.request.get(detailPath)
        expect(response.ok(), await response.text()).toBe(true)
        const po: PurchaseOrderDetail = await response.json()
        return po.xero_id !== null
      },
      { timeout: 90_000, intervals: [1000] },
    )
    .toBe(true)

  await page.goto('/admin/xero')
  await expect(autoId(page, 'XeroPage-last-syncs-row-purchase_orders')).toBeVisible()
  const syncButton = autoId(page, 'XeroPage-start-sync')
  await expect(syncButton).toBeEnabled({ timeout: 300_000 })
  const started = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/xero/sync/' &&
      response.request().method() === 'POST',
  )
  await syncButton.click()
  const syncResponse = await started
  expect(syncResponse.status(), await syncResponse.text()).toBe(202)
  const outcome = page.getByText(/^Xero sync (complete|aborted|failed)$/)
  await expect(outcome).toBeVisible({ timeout: 300_000 })
  await expect(outcome).toHaveText('Xero sync complete')

  await page.goto(poUrl)
  await expect(autoId(page, 'PoSummaryCard-status-trigger')).toHaveText('Fully Received')
  await page.reload()
  await expect(autoId(page, 'PoSummaryCard-status-trigger')).toHaveText('Fully Received')
  const receivedResponse = await page.request.get(detailPath)
  expect(receivedResponse.ok(), await receivedResponse.text()).toBe(true)
  const received: PurchaseOrderDetail = await receivedResponse.json()
  expect(received.lines.map((line) => line.received_quantity)).toEqual([1])

  await page.goto('/purchasing/po')
  await autoId(page, 'PurchaseOrderView-search').fill(received.po_number)
  await expect(autoId(page, `PurchaseOrderView-row-${received.id}`)).toContainText('Fully Received')
})
