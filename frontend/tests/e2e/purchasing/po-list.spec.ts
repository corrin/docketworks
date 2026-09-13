import { test, expect } from '../fixtures/auth'
import { autoId, createTestPurchaseOrder } from '../helpers'

/**
 * The purchase-order list is served one page at a time, and searched by the
 * server.
 *
 * Production holds 990 purchase orders over 2,315 lines. The list endpoint used
 * to return every one of them with their lines prefetched, and the screen had
 * no search at all — so finding an order meant scrolling the whole table
 * (ADR 0054).
 *
 * These assertions state the MECHANISM rather than a row count, so they hold at
 * any volume: the response carries the server's own total, the client renders
 * only the page it was given, and the search term reaches the API instead of
 * filtering rows already loaded. No seeding — the restored database already
 * holds far more orders than one page.
 */
const LIST_PATH = '/api/purchasing/purchase-orders/'

test.describe('Purchase order list', () => {
  test('serves one page and reports the server total', async ({ authenticatedPage: page }) => {
    // Seed past one page (ADR 0054): the assertion below was conditional on the
    // database already holding more than a page, so a thin corpus passed it
    // without exercising paging at all. One order through the UI supplies a
    // supplier; the rest are drafts through the API, which pushes nothing.
    const firstUrl = await createTestPurchaseOrder(page)
    const firstId = new URL(firstUrl).pathname.split('/').at(-1)
    const first = await (await page.request.get(`${LIST_PATH}${firstId}/`)).json()
    for (let index = 0; index < 50; index++) {
      const created = await page.request.post(LIST_PATH, {
        data: { supplier_id: first.supplier_id },
      })
      expect(created.status()).toBe(201)
    }

    const listResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === LIST_PATH &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 30000 },
    )

    await page.goto('/purchasing/po')
    const body = await (await listResponse).json()

    // The envelope, not a bare array — that difference is the whole change.
    expect(body).toHaveProperty('results')
    expect(body).toHaveProperty('count')
    expect(body).toHaveProperty('page_size')
    expect(body).toHaveProperty('total_pages')
    expect(Array.isArray(body.results)).toBe(true)

    // The page is bounded by the size the server chose, and the total is the
    // server's answer rather than the number of rows that happen to be loaded.
    expect(body.results.length).toBeLessThanOrEqual(body.page_size)
    expect(body.count).toBeGreaterThanOrEqual(body.results.length)

    // The client renders exactly the page it was given.
    await expect(page.locator('[data-automation-id^="PurchaseOrderView-row-"]')).toHaveCount(
      body.results.length,
    )

    // More pages exist by construction, so the footer must name the server's
    // total, not the rows on screen — that is what tells an operator the list
    // is partial.
    expect(body.total_pages).toBeGreaterThan(1)
    await expect(autoId(page, 'PurchaseOrderView-load-more')).toContainText(String(body.count))
  })

  test('search narrows on the server, not in the browser', async ({ authenticatedPage: page }) => {
    const firstPage = page.waitForResponse(
      (response) => new URL(response.url()).pathname === LIST_PATH && response.status() === 200,
      { timeout: 30000 },
    )
    await page.goto('/purchasing/po')
    const unfiltered = await (await firstPage).json()
    expect(unfiltered.results.length).toBeGreaterThan(0)
    const target: string = unfiltered.results[0].po_number

    // Armed before typing: the debounce means the request follows the input.
    const searched = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === LIST_PATH &&
        new URL(response.url()).searchParams.get('q') === target &&
        response.status() === 200,
      { timeout: 30000 },
    )
    await autoId(page, 'PurchaseOrderView-search').fill(target)
    const filtered = await (await searched).json()

    // The term reached the API and the server recounted: a client-side filter
    // would leave `count` at the unfiltered total.
    expect(filtered.count).toBeLessThan(unfiltered.count)
    expect(filtered.results.map((row: { po_number: string }) => row.po_number)).toContain(target)

    await expect(page.locator('[data-automation-id^="PurchaseOrderView-row-"]')).toHaveCount(
      filtered.results.length,
    )
  })
})
