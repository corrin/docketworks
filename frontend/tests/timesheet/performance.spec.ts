import { test, expect } from '../fixtures/auth'

/**
 * Performance test for timesheet entry page.
 * Measures page load time and network request timing.
 */

function getWeekdayDate(): string {
  const date = new Date()
  const day = date.getDay()
  if (day === 6) date.setDate(date.getDate() - 1)
  if (day === 0) date.setDate(date.getDate() - 2)
  return date.toISOString().split('T')[0]
}

test.describe('timesheet entry performance', () => {
  test('measure page load time and network requests', async ({ authenticatedPage: page }) => {
    const networkRequests: {
      url: string
      method: string
      startTime: number
      duration?: number
    }[] = []

    const startTime = Date.now()

    // Track all network requests
    page.on('request', (request) => {
      const url = request.url()
      // Only track API requests
      if (url.includes('/api/') || url.includes('/job/') || url.includes('/timesheets/')) {
        networkRequests.push({
          url: url.replace(/.*\/\/[^/]+/, ''), // Remove origin
          method: request.method(),
          startTime: Date.now() - startTime,
        })
      }
    })

    page.on('response', (response) => {
      const url = response.url().replace(/.*\/\/[^/]+/, '')
      const request = networkRequests.find((r) => r.url === url && r.duration === undefined)
      if (request) {
        request.duration = Date.now() - startTime - request.startTime
      }
    })

    // Navigate to daily timesheet first
    const weekday = getWeekdayDate()
    await page.goto(`/timesheets/daily?date=${weekday}`)
    await page.waitForLoadState('networkidle')

    // Click first staff to get staff ID
    const firstStaffRow = page.locator('[data-automation-id^="StaffRow-name-"]').first()
    await firstStaffRow.waitFor({ timeout: 10000 })

    // Get the staff ID directly from the element's automation ID
    const automationId = await firstStaffRow.getAttribute('data-automation-id')
    const staffId = automationId?.replace('StaffRow-name-', '') || ''

    console.log(`\n=== Navigating to timesheet entry for staff: ${staffId} ===\n`)

    // Clear tracked requests before navigating to entry page
    networkRequests.length = 0
    const entryStartTime = Date.now()

    // Navigate directly to the entry page
    await page.goto(`/timesheets/entry?date=${weekday}&staffId=${staffId}`)

    // Wait for grid to appear (indicates data loaded)
    const grid = page.locator('.ag-theme-custom')
    await grid.waitFor({ state: 'visible', timeout: 60000 })

    // Wait for loading spinner to disappear
    await page.waitForFunction(
      () => {
        const spinner = document.querySelector('.animate-spin')
        return !spinner
      },
      { timeout: 60000 },
    )

    const totalLoadTime = Date.now() - entryStartTime

    console.log('\n=== PERFORMANCE REPORT ===\n')
    console.log(
      `Total page load time: ${totalLoadTime}ms (${(totalLoadTime / 1000).toFixed(1)}s)\n`,
    )

    console.log('Network requests (in order):')
    console.log('----------------------------')

    // Sort by start time
    networkRequests.sort((a, b) => a.startTime - b.startTime)

    let totalApiTime = 0
    for (const req of networkRequests) {
      const duration = req.duration || 0
      totalApiTime += duration
      console.log(
        `[${req.startTime}ms] ${req.method} ${req.url.substring(0, 80)}... → ${duration}ms`,
      )
    }

    console.log('\n----------------------------')
    console.log(`Total API time (sum): ${totalApiTime}ms`)
    console.log(`Total page load time: ${totalLoadTime}ms`)
    console.log(`Frontend overhead: ${totalLoadTime - totalApiTime}ms`)
    console.log(`Number of API calls: ${networkRequests.length}`)

    // Check for duplicate API calls
    const urlCounts: Record<string, number> = {}
    for (const req of networkRequests) {
      const baseUrl = req.url.split('?')[0]
      urlCounts[baseUrl] = (urlCounts[baseUrl] || 0) + 1
    }

    const duplicates = Object.entries(urlCounts).filter(([, count]) => count > 1)
    if (duplicates.length > 0) {
      console.log('\nDuplicate API calls detected:')
      for (const [url, count] of duplicates) {
        console.log(`  ${count}x ${url}`)
      }
    }

    // Assertions
    console.log('\n=== ASSERTIONS ===\n')

    // Log if page takes more than 5 seconds
    if (totalLoadTime > 5000) {
      console.log(`WARNING: Page load time (${totalLoadTime}ms) exceeds 5 seconds!`)
    }

    // The test passes but logs all timing info
    expect(grid).toBeVisible()
  })

  test('measure sequential vs parallel API behavior', async ({ authenticatedPage: page }) => {
    const apiTiming: { url: string; start: number; end: number }[] = []

    page.on('request', (request) => {
      const url = request.url()
      if (url.includes('/api/') || url.includes('/job/') || url.includes('/timesheets/')) {
        apiTiming.push({
          url: url.replace(/.*\/\/[^/]+/, ''),
          start: Date.now(),
          end: 0,
        })
      }
    })

    page.on('response', (response) => {
      const url = response.url().replace(/.*\/\/[^/]+/, '')
      const req = apiTiming.find((r) => r.url === url && r.end === 0)
      if (req) {
        req.end = Date.now()
      }
    })

    const weekday = getWeekdayDate()
    await page.goto(`/timesheets/daily?date=${weekday}`)
    await page.waitForLoadState('networkidle')

    const firstStaffRow = page.locator('[data-automation-id^="StaffRow-name-"]').first()
    await firstStaffRow.waitFor({ timeout: 10000 })
    const automationId = await firstStaffRow.getAttribute('data-automation-id')
    const staffId = automationId?.replace('StaffRow-name-', '') || ''

    apiTiming.length = 0

    await page.goto(`/timesheets/entry?date=${weekday}&staffId=${staffId}`)
    await page.locator('.ag-theme-custom').waitFor({ state: 'visible', timeout: 60000 })
    await page.waitForFunction(() => !document.querySelector('.animate-spin'), { timeout: 60000 })

    console.log('\n=== API REQUEST TIMELINE ===\n')

    if (apiTiming.length === 0) {
      console.log('No API requests captured')
      return
    }

    const minStart = Math.min(...apiTiming.map((r) => r.start))

    // Visualize timeline
    for (const req of apiTiming.sort((a, b) => a.start - b.start)) {
      const relStart = req.start - minStart
      const duration = Math.max(0, req.end - req.start)
      const shortUrl = req.url.split('?')[0].substring(0, 50)
      const bar = '█'.repeat(Math.min(50, Math.ceil(duration / 100)))
      console.log(
        `${relStart.toString().padStart(5)}ms: ${shortUrl.padEnd(50)} |${bar}| ${duration}ms`,
      )
    }

    // Check for sequential patterns
    console.log('\n=== SEQUENTIAL VS PARALLEL ANALYSIS ===\n')

    let sequentialCount = 0
    let parallelCount = 0

    for (let i = 1; i < apiTiming.length; i++) {
      const prev = apiTiming[i - 1]
      const curr = apiTiming[i]

      // If current request started after previous ended, it's sequential
      if (curr.start >= prev.end) {
        sequentialCount++
      } else {
        parallelCount++
      }
    }

    console.log(`Sequential request patterns: ${sequentialCount}`)
    console.log(`Parallel request patterns: ${parallelCount}`)

    if (sequentialCount > parallelCount * 2) {
      console.log('\nWARNING: Requests appear to be mostly sequential - could be parallelized!')
    }

    expect(page.locator('.ag-theme-custom')).toBeVisible()
  })
})
