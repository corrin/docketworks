import type { Page } from '@playwright/test'
import type {
  PurchaseOrderDetail,
  PurchaseOrderListResponse,
} from '../../../src/api/generated/types.gen'
import { expect, test } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder, waitForPoAutosave } from '../helpers'

/** One page of the submitted orders, as the list endpoint serves them. */
async function submittedOrders(page: Page, pageNumber: number): Promise<PurchaseOrderListResponse> {
  const response = await page.request.get(
    `/api/purchasing/purchase-orders/?status=submitted&page_size=50&page=${pageNumber}`,
  )
  expect(response.ok(), await response.text()).toBe(true)
  const listed: PurchaseOrderListResponse = await response.json()
  return listed
}

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

  // A status transition pushes as it happens, and a draft pushes nothing at
  // all, which is what the two null assertions above prove. So Xero's own
  // status arriving is proof that the RECEIVED version is the one that reached
  // it. The poll only absorbs the autosave settling; an outage would leave the
  // call owed to the hourly sync, and this spec would rightly fail on it.
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

// Opus: every other purchase-order spec raises its own order, so the only push
// they exercise is a create. An office receipts orders that were sent weeks
// ago, and for those Xero already holds the document: the push is an update of
// it. That only replays faithfully when the fake holds the order too, which is
// what the restore seed's purchase-order phase provides. Without it the fake
// has never heard of the order's Xero id and refuses the update.
test('receiving an order Xero already held updates it in place', async ({
  authenticatedPage: page,
}) => {
  // Ours (the instance prefix and digits only), not a [TEST] order another
  // spec raised and not one Xero raised: those Docketworks does not push.
  // Every page, not just the first: the list is newest first, so the restored
  // orders this test needs sit at the back of it, and an instance carrying more
  // than one page of submitted orders would never reach them.
  let held: PurchaseOrderDetail | null = null
  const firstPage = await submittedOrders(page, 1)
  for (let pageNumber = 1; pageNumber <= firstPage.total_pages && held === null; pageNumber++) {
    const listed = pageNumber === 1 ? firstPage : await submittedOrders(page, pageNumber)
    for (const row of listed.results.filter((each) => /^JO-\d{4}$/.test(each.po_number))) {
      const response = await page.request.get(`/api/purchasing/purchase-orders/${row.id}/`)
      expect(response.ok(), await response.text()).toBe(true)
      const detail: PurchaseOrderDetail = await response.json()
      // Every line costed: the receipt prices the stock it creates, and refuses
      // a line with no cost. That refusal is the application's own and has its
      // own tests; this one is about what reaches Xero.
      const receivable = detail.lines.every((line) => Number(line.unit_cost) > 0)
      if (detail.xero_id !== null && receivable) {
        held = detail
        break
      }
    }
  }
  // Fail early: no such order means the restore seed left the orders out of
  // Xero, which is the defect this test exists to catch.
  if (held === null) {
    throw new Error('No submitted, costed order of ours carries a Xero id; run the restore seed')
  }
  const before: PurchaseOrderDetail = held
  test.info().annotations.push({ type: 'order', description: before.po_number })
  console.log(`[po-receipt-sync] receiving restored order ${before.po_number}`)
  const detailPath = `/api/purchasing/purchase-orders/${before.id}/`

  await page.goto(`/purchasing/po/${before.id}`)
  await autoId(page, 'PoSummaryCard-status-trigger').click()
  const receiptSaved = waitForPoAutosave(page)
  await autoId(page, 'PoSummaryCard-status-fully_received').click()
  await receiptSaved
  await expect(autoId(page, 'PoSummaryCard-status-trigger')).toHaveText('Fully Received')

  // `xero_status` proves nothing here: Xero already held this order, so it
  // answered AUTHORISED before the receipt. The push writes
  // `xero_last_synced` and runs inside the save awaited above, so one read
  // shows whether the receipt reached Xero. An inbound sync landing mid-test
  // writes the same column and would also satisfy this: `xero_push_due` is the
  // exact signal and the detail schema does not expose it.
  const afterResponse = await page.request.get(detailPath)
  expect(afterResponse.ok(), await afterResponse.text()).toBe(true)
  const after: PurchaseOrderDetail = await afterResponse.json()
  expect(after.xero_last_synced).not.toBeNull()
  expect(after.xero_last_synced).not.toBe(before.xero_last_synced)

  // The same document, moved on: a second id would be a duplicate order in
  // Xero for a supplier's bill to match against.
  expect(after.xero_id).toBe(before.xero_id)
  expect(after.xero_status).toBe('AUTHORISED')
  expect(after.status).toBe('fully_received')
})
