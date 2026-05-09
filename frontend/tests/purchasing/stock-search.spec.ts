import { test, expect } from '../fixtures/auth'

/**
 * Stock search E2E (Trello #150).
 *
 * Pins the full-stack contract for the new server-side FTS endpoint:
 *
 * 1. Typing 3+ characters fires exactly one request to
 *    `/api/purchasing/stock/search/` after the 300ms debounce, with the
 *    final query as `q`.
 * 2. The response shape is `{results, count, page, page_size, total_pages}`
 *    and the table renders rows whose description matches.
 *
 * Why this lives at the E2E layer despite cheaper unit / integration tests
 * existing: the original bug was a silent 500 from the view re-validating
 * its own response payload through a write serializer. Vitest mocked the
 * API, so the bug was invisible there. The Django view-layer test
 * (`test_view_returns_search_results_via_http`) catches that specific
 * regression now, but only this E2E confirms the full path — debounced
 * input → axios → DRF → serializer → JSON → table render — actually
 * works end to end.
 */
test.describe('Stock search', () => {
  test('typing a 3-character query populates the table from the FTS endpoint', async ({
    authenticatedPage: page,
  }) => {
    // Navigate to the Stock page
    await page.goto('/purchasing/stock')

    // Wait for the initial all-stock fetch so the table has settled
    await page.waitForResponse(
      (response) =>
        response.url().includes('/api/purchasing/stock/') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 15000 },
    )

    // Capture the search request triggered by debounced typing
    const searchResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes('/api/purchasing/stock/search/') &&
        response.url().includes('q=5mm') &&
        response.status() === 200,
      { timeout: 10000 },
    )

    const input = page.locator('input[placeholder="Search stock items..."]')
    await input.fill('5mm')

    const searchResponse = await searchResponsePromise
    const body = await searchResponse.json()

    // Response envelope contract
    expect(body).toHaveProperty('results')
    expect(body).toHaveProperty('count')
    expect(body).toHaveProperty('total_pages')
    expect(Array.isArray(body.results)).toBe(true)

    // The seed/prod-restore data has plenty of `5mm` items; assert at least one
    // and assert every returned description contains the FTS lexeme. Using
    // /5mm/i not /\b5mm\b/ because Postgres lexes `5mm` as one numword and
    // we don't care which word boundary it sits inside.
    expect(body.count).toBeGreaterThan(0)
    for (const row of body.results) {
      const haystack = [row.description, row.metal_type, row.alloy, row.specifics, row.location]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      expect(haystack).toMatch(/5mm/i)
    }

    // The table should render the new variant-disambiguation columns.
    await expect(page.locator('thead th', { hasText: 'Metal' })).toBeVisible()
    await expect(page.locator('thead th', { hasText: 'Alloy' })).toBeVisible()
    await expect(page.locator('thead th', { hasText: 'Spec' })).toBeVisible()

    // At least one body row visible, and the description column shows the match
    const firstRowDescription = await page
      .locator('tbody tr')
      .first()
      .locator('td')
      .nth(1)
      .textContent()
    expect(firstRowDescription?.toLowerCase()).toContain('5mm')

    // No "No items found" empty state when the search matched.
    await expect(page.locator('text=No stock items found')).toHaveCount(0)
  })

  test('clearing the search box returns to the unfiltered store list without hitting the search endpoint', async ({
    authenticatedPage: page,
  }) => {
    await page.goto('/purchasing/stock')

    // Wait for initial list load
    await page.waitForResponse(
      (response) =>
        response.url().includes('/api/purchasing/stock/') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 15000 },
    )

    const input = page.locator('input[placeholder="Search stock items..."]')

    // Run a search
    const searchPromise = page.waitForResponse(
      (response) =>
        response.url().includes('/api/purchasing/stock/search/') &&
        response.url().includes('q=5mm'),
      { timeout: 10000 },
    )
    await input.fill('5mm')
    await searchPromise

    // Track whether any further /search/ request fires when we clear the box.
    let postClearSearchCalls = 0
    page.on('response', (response) => {
      if (
        response.url().includes('/api/purchasing/stock/search/') &&
        !response.url().includes('q=5mm')
      ) {
        postClearSearchCalls += 1
      }
    })

    await input.fill('')

    // Wait past the debounce window so any spurious request would have fired.
    // 300ms debounce + headroom for the listener to observe the response.
    await page.waitForTimeout(800)

    expect(postClearSearchCalls).toBe(0)

    // The table is still populated (from the cached store list).
    await expect(page.locator('tbody tr').first()).toBeVisible()
  })
})
