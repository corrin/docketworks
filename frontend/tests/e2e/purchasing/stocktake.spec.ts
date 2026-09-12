import { test, expect } from '../fixtures/auth'
import type { Page } from '@playwright/test'
import { strongResourceVersion } from '../../../src/lib/concurrency/interceptors'

async function setupStocktake(page: Page) {
  await expect(page.getByText('Loading stocktake setup…')).toHaveCount(0)
  const setup = page.getByRole('button', { name: 'Set up stocktake', exact: true })
  if (await setup.isVisible()) await setup.click()
  await expect(page.getByRole('button', { name: 'New stocktake', exact: true })).toBeEnabled()
}

// Physical corrections must be reachable from navigation and survive the complete UI/API round trip.
test('find a sheet, post once, and correct the count without losing history', async ({
  authenticatedPage: page,
}, testInfo) => {
  await page.goto('/purchasing/stock')
  await page.getByRole('button', { name: 'Purchases', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Stocktake', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Stocktake', exact: true })).toBeVisible()
  await setupStocktake(page)
  await page.getByRole('button', { name: 'New stocktake', exact: true }).click()
  await page.getByRole('button', { name: 'Add found item', exact: true }).click()
  const item = `E2E stocktake 0.6mm sheet ${Date.now()}`
  await page.getByLabel('Item description', { exact: true }).fill(item)
  await page.getByLabel('Count location', { exact: true }).fill('E2E Rack 3')
  await expect(page.getByLabel('Counted quantity', { exact: true })).toHaveValue('')
  await page.getByLabel('Counted quantity', { exact: true }).fill('1')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.getByText('Enter a unit cost for every found item.')).toBeVisible()
  await page.getByLabel('Unit cost', { exact: true }).fill('80')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeEnabled()
  await page.reload()
  await expect(page.getByLabel('Counted quantity', { exact: true })).toHaveValue('1')
  for (const width of [1366, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`stocktake-${width}.png`), fullPage: true })
  }
  await page.setViewportSize({ width: 1366, height: 900 })
  await page.getByRole('button', { name: 'Post stocktake', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Posted movements', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '0 → 1', exact: true })).toBeVisible()
  await expect(page.getByLabel('Counted quantity', { exact: true })).toHaveAttribute('readonly')
  const originalUrl = page.url()
  await page.reload()
  await expect(page.getByRole('cell', { name: '0 → 1', exact: true })).toHaveCount(1)
  await page.getByRole('button', { name: 'Create correction', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Original stocktake', exact: true })).toHaveAttribute(
    'href',
    new URL(originalUrl).pathname,
  )
  await expect(page.getByLabel('Counted quantity', { exact: true })).toHaveValue('')
  await page.getByLabel('Counted quantity', { exact: true }).fill('0')
  await page.getByLabel('Difference reason', { exact: true }).fill('Unexplained shortage')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Post stocktake', exact: true }).click()
  await expect(page.getByRole('cell', { name: '1 → 0', exact: true })).toBeVisible()
  await page.goto('/purchasing/stock')
  await page.getByRole('textbox', { name: 'Search stock items', exact: true }).fill(item)
  const stockRow = page.getByRole('row').filter({ hasText: item })
  await expect(stockRow).toHaveCount(1)
  await expect(stockRow.locator('[data-automation-id="StockView-quantity"]')).toHaveText('0')
  await stockRow.getByRole('button', { name: 'Record count', exact: true }).click()
  await expect(page.getByLabel('Item description', { exact: true })).toHaveValue(item)
  await expect(page.getByLabel('Counted quantity', { exact: true })).toHaveValue('')
  await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeDisabled()
  await page.goto('/purchasing/stock')
  await page.getByRole('textbox', { name: 'Search stock items', exact: true }).fill(item)
  await stockRow.getByRole('button', { name: 'Retire empty identity', exact: true }).click()
  await expect(stockRow).toHaveCount(0)
  await page.getByRole('checkbox', { name: 'Include retired identities' }).check()
  await expect(stockRow).toContainText('Retired')
  await expect(stockRow.getByRole('button', { name: 'Record count', exact: true })).toHaveCount(0)
  await stockRow.getByRole('button', { name: 'History', exact: true }).click()
  const history = page.getByRole('dialog')
  await expect(history.getByRole('cell', { name: '0 → 1', exact: true })).toBeVisible()
  await expect(history.getByRole('cell', { name: '1 → 0', exact: true })).toBeVisible()
  await page.reload()
  await expect(history.getByRole('heading', { name: 'Stock movements', exact: true })).toBeVisible()
  await expect(history.getByRole('cell', { name: '1 → 0', exact: true })).toBeVisible()
  await history.getByRole('button', { name: 'Close history', exact: true }).click()
  await expect(history).toHaveCount(0)
})

test('a multi-item count preserves blank entries and the count list stays paged', async ({
  authenticatedPage: page,
}) => {
  await page.goto('/purchasing/stocktakes')
  await setupStocktake(page)
  await page.getByRole('button', { name: 'New stocktake', exact: true }).click()
  const prefix = `[TEST] Stocktake batch ${Date.now()}`
  for (let index = 0; index < 2; index++) {
    await page.getByRole('button', { name: 'Add found item', exact: true }).click()
    await page.getByLabel('Item description', { exact: true }).nth(index).fill(`${prefix} ${index}`)
    await page.getByLabel('Counted quantity', { exact: true }).nth(index).fill('1')
    await page.getByLabel('Unit cost', { exact: true }).nth(index).fill('80')
  }
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeEnabled()
  const countId = new URL(page.url()).pathname.split('/').pop()
  const countResponse = await page.request.get(`/api/purchasing/stocktakes/${countId}/`)
  const countVersion = strongResourceVersion(countResponse.headers())
  if (countVersion === null) throw new Error('Stocktake response has no strong resource version')
  const postings = await Promise.all(
    [0, 1].map(() =>
      page.request.post(`/api/purchasing/stocktakes/${countId}/post/`, {
        headers: { 'If-Match': countVersion },
      }),
    ),
  )
  for (const posting of postings) {
    expect(posting.status()).toBe(200)
    expect((await posting.json()).id).toBe(countId)
  }
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Posted movements', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '0 → 1', exact: true })).toHaveCount(2)
  await page.getByRole('link', { name: 'Stocktakes', exact: true }).click()
  await page.getByRole('button', { name: 'New stocktake', exact: true }).click()
  await page.getByRole('button', { name: 'Add stock to count', exact: true }).click()
  await page.getByRole('textbox', { name: 'Search stock', exact: true }).fill(prefix)
  await expect(page.getByRole('button', { name: 'Add to count', exact: true })).toHaveCount(2)
  await page.getByRole('button', { name: 'Add to count', exact: true }).first().click()
  await page.getByRole('button', { name: 'Add to count', exact: true }).click()
  await page.getByRole('button', { name: 'Hide stock search', exact: true }).click()
  await page.getByLabel('Counted quantity', { exact: true }).first().fill('0')
  await page.getByLabel('Difference reason', { exact: true }).first().fill('Unexplained shortage')
  await expect(page.getByLabel('Counted quantity', { exact: true }).nth(1)).toHaveValue('')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeEnabled()
  await page.reload()
  await page.getByRole('button', { name: 'Post stocktake', exact: true }).click()
  await expect(page.getByRole('cell', { name: '1 → 0', exact: true })).toHaveCount(1)

  // Seed past one page through the same draft-creation API used by the UI.
  for (let index = 0; index < 51; index++) {
    const created = await page.request.post('/api/purchasing/stocktakes/', { data: {} })
    expect(created.status()).toBe(200)
  }
  await page.getByRole('link', { name: 'Stocktakes', exact: true }).click()
  await expect(page.locator('tbody tr')).toHaveCount(50)
  const scroll = page.locator('table').locator('..')
  expect(await scroll.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true)
  const nextPage = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/purchasing/stocktakes/' && url.searchParams.get('page') === '2'
  })
  await scroll.evaluate((element) => {
    element.scrollTop = element.scrollHeight
  })
  const response = await nextPage
  expect(response.status()).toBe(200)
  await expect(page.locator('tbody tr')).not.toHaveCount(50)
  await expect(page.locator('[data-automation-id="StocktakeList-load-more-count"]')).toContainText(
    'stocktakes',
  )
})

test.describe('stocktake conflict recovery', () => {
  test.use({ expectedConsoleErrors: [/Failed to load resource.*status of 412/] })

  test('a stale draft retains edits until the operator reloads the saved draft', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/purchasing/stocktakes')
    await setupStocktake(page)
    await page.getByRole('button', { name: 'New stocktake', exact: true }).click()
    await page.getByRole('button', { name: 'Add found item', exact: true }).click()
    const description = page.getByLabel('Item description', { exact: true })
    await description.fill(`[TEST] Conflict ${Date.now()}`)
    await page.getByLabel('Counted quantity', { exact: true }).fill('1')
    await page.getByLabel('Unit cost', { exact: true }).fill('80')
    await page.getByRole('button', { name: 'Save draft', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeEnabled()
    const id = new URL(page.url()).pathname.split('/').pop()
    const url = `/api/purchasing/stocktakes/${id}/`
    const detail = await page.request.get(url)
    const version = strongResourceVersion(detail.headers())
    if (version === null) throw new Error('Stocktake response has no strong resource version')
    const body = await detail.json()
    body.lines[0].description = '[TEST] Saved by another operator'
    const otherSave = await page.request.put(url, {
      headers: { 'If-Match': version },
      data: { lines: body.lines },
    })
    expect(otherSave.status()).toBe(200)
    await description.fill('[TEST] Retained local edits')
    const refused = page.waitForResponse(
      (response) => response.url().endsWith(url) && response.request().method() === 'PUT',
    )
    await page.getByRole('button', { name: 'Save draft', exact: true }).click()
    expect((await refused).status()).toBe(412)
    await expect(description).toHaveValue('[TEST] Retained local edits')
    await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Reload saved draft', exact: true }).click()
    await expect(description).toHaveValue('[TEST] Saved by another operator')
    await description.fill('[TEST] Reviewed final version')
    await page.getByRole('button', { name: 'Save draft', exact: true }).click()
    // Save draft goes disabled the instant the PUT leaves, because its disabled
    // state doubles as its in-flight state, so waiting on it would pass while the
    // write is still open and the read below would race the transaction. Post
    // stocktake needs the request finished AND the form clean, so it can only be
    // enabled once the save was accepted.
    await expect(page.getByRole('button', { name: 'Post stocktake', exact: true })).toBeEnabled()
    expect((await (await page.request.get(url)).json()).lines[0].description).toBe(
      '[TEST] Reviewed final version',
    )
  })
})
