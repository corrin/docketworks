import { test, expect } from '../fixtures/auth'
import { autoId } from '../helpers'
import { zStockSearchResponse } from '../../../src/api/generated/zod.gen'

/** GPT: Exercise the real response because mocked search missed a response-serialization 500. */
test('stock search ranks matches, bounds the table and restores the unfiltered total', async ({
  authenticatedPage: page,
}) => {
  const initialResponse = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return (
      url.pathname === '/api/purchasing/stock/' &&
      !url.searchParams.get('q') &&
      response.request().method() === 'GET'
    )
  })
  await page.goto('/purchasing/stock')
  const initial = await initialResponse
  expect(initial.status()).toBe(200)
  const unfiltered = zStockSearchResponse.parse(await initial.json())
  const total = autoId(page, 'StockView-load-more-count')
  await expect(total).toContainText(`of ${unfiltered.count} stock items`)

  const searchResponse = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return (
      url.pathname === '/api/purchasing/stock/' &&
      url.searchParams.get('q') === '5mm' &&
      response.request().method() === 'GET'
    )
  })
  await autoId(page, 'StockView-search').fill('5mm')
  const searched = await searchResponse
  expect(searched.status()).toBe(200)
  const matches = zStockSearchResponse.parse(await searched.json())
  expect(matches.count).toBeGreaterThan(0)
  expect(matches.results.length).toBeLessThanOrEqual(matches.page_size)
  await expect(total).toContainText(`of ${matches.count} stock items`)
  await expect(autoId(page, 'StockView-description').first()).toHaveText(
    matches.results.slice(0, 1).map((row) => row.description),
  )
  const descriptions = await autoId(page, 'StockView-description').allTextContents()
  expect(descriptions.slice(0, 5).some((description) => /5(?:\.0+)?mm/i.test(description))).toBe(
    true,
  )

  await autoId(page, 'StockView-search').fill('')
  await expect(total).toContainText(`of ${unfiltered.count} stock items`)
  await expect(autoId(page, 'StockView-description').first()).toHaveText(
    unfiltered.results.slice(0, 1).map((row) => row.description),
  )
  const scroll = autoId(page, 'StockView-table').locator('..')
  expect(
    await scroll.evaluate((element) => {
      const style = getComputedStyle(element)
      return style.maxHeight !== 'none' && style.overflowY === 'auto'
    }),
  ).toBe(true)
})
