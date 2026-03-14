/**
 * Throwaway diagnostic scripts to reproduce and confirm drag-and-drop bugs.
 *
 * Bug 1: isDragging stays true after drop — columns remain blue-highlighted.
 * Bug 2: Stale SortableJS instances after layout switch (v-if destroys/remounts DOM).
 * Bug 3: Rapid layout switching breaks drag-and-drop entirely.
 *
 * Failures confirm the bugs exist. Passes mean the bugs can't be reproduced.
 */
import { test, expect } from '../fixtures/auth'
import type { Page, Locator } from '@playwright/test'

const DESKTOP_VIEWPORT = { width: 1280, height: 720 }
const TABLET_VIEWPORT = { width: 768, height: 1024 }

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) throw new Error(`Unable to parse job id from url: ${url}`)
  return match[1]
}

const getVisibleJobCard = (page: Page, jobId: string): Locator =>
  page.locator(`[data-job-id="${jobId}"]:visible`).first()

const getVisibleColumns = (page: Page): Locator => page.locator('[data-status]:visible')

const getJobColumn = (page: Page, jobId: string): Locator =>
  getVisibleColumns(page)
    .filter({ has: getVisibleJobCard(page, jobId) })
    .first()

const pickTargetColumn = async (
  page: Page,
  currentStatus: string | null,
): Promise<{ column: Locator; status: string }> => {
  const preferredStatus = 'in_progress'
  if (currentStatus !== preferredStatus) {
    const preferredColumn = page.locator(`[data-status="${preferredStatus}"]:visible`)
    if (await preferredColumn.count()) {
      return { column: preferredColumn.first(), status: preferredStatus }
    }
  }

  const columns = getVisibleColumns(page)
  const columnCount = await columns.count()

  for (let i = 0; i < columnCount; i += 1) {
    const column = columns.nth(i)
    const status = await column.getAttribute('data-status')
    if (status && status !== currentStatus) {
      return { column, status }
    }
  }

  throw new Error('Unable to find target column for status change')
}

const dragCardToColumn = async (page: Page, card: Locator, column: Locator) => {
  await card.scrollIntoViewIfNeeded()
  await column.scrollIntoViewIfNeeded()

  const cardBox = await card.boundingBox()
  const columnBox = await column.boundingBox()

  if (!cardBox || !columnBox) throw new Error('Unable to resolve drag and drop positions')

  const startX = cardBox.x + cardBox.width / 2
  const startY = cardBox.y + cardBox.height / 2
  const endX = columnBox.x + Math.min(60, columnBox.width / 2)
  const endY = columnBox.y + 60

  // Fast drag — just enough hold for browser to initiate native drag, then quick move + release
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.waitForTimeout(150)

  const steps = 8
  for (let i = 1; i <= steps; i++) {
    const t = i / steps
    await page.mouse.move(startX + (endX - startX) * t, startY + (endY - startY) * t)
    await page.waitForTimeout(8)
  }

  await page.mouse.up()
  await page.waitForTimeout(300)
}

/** Collect diagnostic state for isDragging, column highlights, and stuck card classes */
const getDragDiagnostics = async (page: Page, jobId?: string) => {
  return page.evaluate(
    ({ jobId }) => {
      const bodyHasDragClass = document.body.classList.contains('is-dragging')
      const allColumns = document.querySelectorAll('[data-status]')
      const highlightedColumns: string[] = []
      allColumns.forEach((col) => {
        if (col.classList.contains('bg-blue-50')) {
          highlightedColumns.push(col.getAttribute('data-status') || 'unknown')
        }
      })

      // Check for stuck SortableJS classes on the dragged card
      const stuckCards: { jobId: string; classes: string[] }[] = []
      const sortableClasses = ['sortable-chosen', 'sortable-drag', 'sortable-ghost']
      const selector = jobId ? `[data-job-id="${jobId}"]` : '.job-card'
      document.querySelectorAll(selector).forEach((card) => {
        const stuck = sortableClasses.filter((cls) => card.classList.contains(cls))
        if (stuck.length > 0) {
          stuckCards.push({
            jobId: card.getAttribute('data-job-id') || 'unknown',
            classes: stuck,
          })
        }
      })

      return { bodyHasDragClass, highlightedColumns, stuckCards }
    },
    { jobId },
  )
}

test.describe('debug: drag-and-drop bugs', () => {
  test('isDragging stuck after drop', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-status')
    const { column: targetColumn } = await pickTargetColumn(page, sourceStatus)

    // Try to catch the API response, but don't hard-fail if drag was too fast for SortableJS
    let dropCompleted = false
    const statusResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/job/api/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300,
    )

    await dragCardToColumn(page, jobCard, targetColumn)

    try {
      await Promise.race([
        statusResponsePromise.then(() => {
          dropCompleted = true
        }),
        page.waitForTimeout(5000),
      ])
    } catch {
      // timeout — drop didn't fire
    }

    console.log(`[DEBUG] Drop completed (API called): ${dropCompleted}`)

    // Wait 3s for any async cleanup / safety timeout to settle
    await page.waitForTimeout(3000)

    // Diagnose drag state — this is the key check regardless of whether drop completed
    const diag = await getDragDiagnostics(page, jobId)
    console.log('[DEBUG] isDragging diagnostics after drop:', JSON.stringify(diag, null, 2))

    // These assertions will FAIL if the bug is present
    expect(diag.bodyHasDragClass, 'body should NOT have is-dragging class after drop').toBe(false)
    expect(
      diag.highlightedColumns.length,
      `No columns should have bg-blue-50 highlight, but found: ${diag.highlightedColumns.join(', ')}`,
    ).toBe(0)
    expect(
      diag.stuckCards.length,
      `No cards should have stuck sortable classes, but found: ${JSON.stringify(diag.stuckCards)}`,
    ).toBe(0)
  })

  test('stale sortable after layout switch', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    // Step 1: Start at desktop viewport
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    // Step 2: First drag-and-drop at desktop — confirm it works
    const sourceColumn1 = getJobColumn(page, jobId)
    const sourceStatus1 = await sourceColumn1.getAttribute('data-status')
    const { column: targetColumn1, status: targetStatus1 } = await pickTargetColumn(
      page,
      sourceStatus1,
    )

    const statusResponse1 = page.waitForResponse(
      (response) =>
        response.url().includes(`/job/api/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300,
    )

    await dragCardToColumn(page, jobCard, targetColumn1)
    await statusResponse1
    console.log(`[DEBUG] First drag succeeded: ${sourceStatus1} → ${targetStatus1}`)

    await page.waitForTimeout(1000)

    // Step 3: Resize to tablet — triggers v-if layout switch (destroys desktop DOM)
    console.log('[DEBUG] Switching to tablet viewport...')
    await page.setViewportSize(TABLET_VIEWPORT)
    await page.waitForTimeout(2000) // Wait for Vue to remount tablet layout

    // Step 4: Resize back to desktop — new DOM elements
    console.log('[DEBUG] Switching back to desktop viewport...')
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.waitForTimeout(2000) // Wait for Vue to remount desktop layout

    // Step 5: Attempt another drag-and-drop
    const jobCard2 = getVisibleJobCard(page, jobId)
    await expect(jobCard2).toBeVisible({ timeout: 15000 })

    const sourceColumn2 = getJobColumn(page, jobId)
    const sourceStatus2 = await sourceColumn2.getAttribute('data-status')
    const { column: targetColumn2, status: targetStatus2 } = await pickTargetColumn(
      page,
      sourceStatus2,
    )

    const statusResponse2 = page.waitForResponse(
      (response) =>
        response.url().includes(`/job/api/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300,
    )

    await dragCardToColumn(page, jobCard2, targetColumn2)

    // Check if drag succeeded (card moved to target column)
    let dragSucceeded = false
    try {
      await statusResponse2
      await expect(
        page.locator(`[data-status="${targetStatus2}"] [data-job-id="${jobId}"]:visible`),
      ).toBeVisible({ timeout: 15000 })
      dragSucceeded = true
    } catch {
      console.log('[DEBUG] Second drag FAILED — likely stale sortable instance')
    }

    console.log(`[DEBUG] Second drag (after layout switch): ${dragSucceeded ? 'PASSED' : 'FAILED'}`)

    // Wait for settle
    await page.waitForTimeout(2000)

    // Check drag state cleanup
    const diag = await getDragDiagnostics(page)
    console.log('[DEBUG] Post-layout-switch diagnostics:', JSON.stringify(diag, null, 2))

    // Check if sortable containers are connected to DOM
    // Note: :visible is a Playwright pseudo-selector, not valid in native querySelectorAll
    const sortableCheck = await page.evaluate(() => {
      const columns = document.querySelectorAll('[data-status]')
      const results: {
        status: string
        isConnected: boolean
        childCount: number
        visible: boolean
      }[] = []
      columns.forEach((col) => {
        const el = col as HTMLElement
        const visible = el.offsetParent !== null || el.getClientRects().length > 0
        results.push({
          status: el.dataset.status || 'unknown',
          isConnected: el.isConnected,
          childCount: el.querySelectorAll('.job-card').length,
          visible,
        })
      })
      return results
    })
    console.log('[DEBUG] Sortable container check:', JSON.stringify(sortableCheck, null, 2))

    expect(dragSucceeded, 'Drag-and-drop should work after layout switch').toBe(true)
    expect(diag.bodyHasDragClass, 'body should NOT have is-dragging class').toBe(false)
    expect(diag.highlightedColumns.length, 'No columns should be highlighted').toBe(0)
  })

  test('rapid layout switching stress test', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    // Start at desktop
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    // Rapidly toggle viewport between desktop and tablet 5 times
    console.log('[DEBUG] Starting rapid layout switching...')
    for (let i = 0; i < 5; i++) {
      await page.setViewportSize(TABLET_VIEWPORT)
      await page.waitForTimeout(300)
      await page.setViewportSize(DESKTOP_VIEWPORT)
      await page.waitForTimeout(300)
      console.log(`[DEBUG] Layout switch cycle ${i + 1}/5`)
    }

    // Settle at desktop
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.waitForTimeout(2000)

    // Attempt drag-and-drop
    const jobCardAfter = getVisibleJobCard(page, jobId)
    await expect(jobCardAfter).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-status')
    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    const statusResponse = page.waitForResponse(
      (response) =>
        response.url().includes(`/job/api/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300,
    )

    await dragCardToColumn(page, jobCardAfter, targetColumn)

    let dragSucceeded = false
    try {
      await statusResponse
      await expect(
        page.locator(`[data-status="${targetStatus}"] [data-job-id="${jobId}"]:visible`),
      ).toBeVisible({ timeout: 15000 })
      dragSucceeded = true
    } catch {
      console.log('[DEBUG] Drag after rapid switching FAILED')
    }

    console.log(`[DEBUG] Drag after rapid switching: ${dragSucceeded ? 'PASSED' : 'FAILED'}`)

    await page.waitForTimeout(2000)

    const diag = await getDragDiagnostics(page)
    console.log('[DEBUG] Post-stress-test diagnostics:', JSON.stringify(diag, null, 2))

    expect(dragSucceeded, 'Drag should work after rapid layout switching').toBe(true)
    expect(diag.bodyHasDragClass, 'body should NOT have is-dragging class').toBe(false)
    expect(diag.highlightedColumns.length, 'No columns should be highlighted').toBe(0)
  })
})
