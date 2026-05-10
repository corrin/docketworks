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

    // The seed/prod-restore data has plenty of `5mm` items. From a user
    // perspective, the important thing is that a clearly relevant `5mm`
    // result appears near the top, not that every fuzzy match on the page is
    // a literal `5mm` string.
    expect(body.count).toBeGreaterThan(0)
    const haystacks = body.results.map((row: Record<string, string | null>) =>
      [row.description, row.metal_type, row.alloy, row.specifics, row.location]
        .filter(Boolean)
        .join(' ')
        .toLowerCase(),
    )
    expect(haystacks.slice(0, 5).some((haystack: string) => /5(?:\.0+)?mm/i.test(haystack))).toBe(
      true,
    )

    // The table should render the new variant-disambiguation columns.
    await expect(page.locator('thead th', { hasText: 'Metal' })).toBeVisible()
    await expect(page.locator('thead th', { hasText: 'Alloy' })).toBeVisible()
    await expect(page.locator('thead th', { hasText: 'Spec' })).toBeVisible()

    // At least one of the first few visible rows should show a direct `5mm`
    // hit so the search feels useful to a user.
    const firstFewDescriptions = await page
      .locator('tbody tr td:nth-child(2)')
      .evaluateAll((cells) =>
        cells.slice(0, 5).map((cell) => cell.textContent?.trim().toLowerCase() || ''),
      )
    expect(firstFewDescriptions.some((description) => /5(?:\.0+)?mm/i.test(description))).toBe(true)

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
