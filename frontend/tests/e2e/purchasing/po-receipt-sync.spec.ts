import type { PurchaseOrderDetail } from '../../../src/api/generated/types.gen'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder, waitForPoAutosave } from '../helpers'

// GPT: letting Xero AUTHORISED overwrite a receipt would revert both visible
// labels, even though the receipt quantity survives.
//
// Opus: this used to click the admin Start Sync button to get Xero's answer
// back, which pulled the whole organisation — every contact, invoice and quote
// — to check one order, waited on a lock any scheduled run holds, and took
// minutes. Xero answers a write by returning the order it stored, so the push
// already carries its answer; `xero_status` and `xero_last_synced` below are
// that answer, recorded by the push itself. Nothing is fetched.
test('a fully received order keeps its receipt when Xero answers AUTHORISED', async ({
  authenticatedPage: page,
}) => {
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
  expect(draft.xero_status).toBeNull()

  await autoId(page, 'PoSummaryCard-status-trigger').click()
  const receiptSaved = waitForPoAutosave(page)
  await autoId(page, 'PoSummaryCard-status-fully_received').click()
  await receiptSaved
  await expect(autoId(page, 'PoSummaryCard-status-trigger')).toHaveText('Fully Received')

  // The push is queued on commit, so this polls rather than waits on a
  // response. Draft edits queue no push at all, so Xero's own status
  // arriving is proof that the RECEIVED version is the one that reached it.
  let pushed: PurchaseOrderDetail | null = null
  await expect
    .poll(
      async () => {
        const response = await page.request.get(detailPath)
        expect(response.ok(), await response.text()).toBe(true)
        pushed = await response.json()
        return pushed?.xero_status
      },
      { timeout: 90_000, intervals: [1000] },
    )
    .toBe('AUTHORISED')

  const echoed = pushed as PurchaseOrderDetail | null
  expect(echoed?.xero_id).not.toBeNull()
  expect(echoed?.xero_last_synced).not.toBeNull()

  // Xero said AUTHORISED and we recorded it. The receipt is ours to keep:
  // whether the goods arrived is a fact Xero does not hold (KAN-144).
  expect(echoed?.status).toBe('fully_received')

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
