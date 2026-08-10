/**
 * Throwaway diagnostic scripts to reproduce and confirm drag-and-drop bugs.
 *
 * Bug 1: isDragging stays true after drop — columns remain blue-highlighted.
 * Bug 2: Stale drag registrations after layout switch (a remounted column
 * re-registers its draggable/dropTarget cleanly, or it doesn't).
 * Bug 3: Rapid layout switching breaks drag-and-drop entirely.
 *
 * Failures confirm the bugs exist. Passes mean the bugs can't be reproduced.
 */
import debug from 'debug'
import type { Page } from '@playwright/test'

import { expect, test } from '../fixtures/auth'
import { expectStepUnder, getJobIdFromUrl } from '../helpers'
import {
  dragCardToColumn,
  FAST_DRAG_TIMING,
  getJobColumn,
  getVisibleJobCard,
  pickTargetColumn,
} from './support'

const log = debug('e2e:kanban')

const DESKTOP_VIEWPORT = { width: 1280, height: 720 }
const TABLET_VIEWPORT = { width: 768, height: 1024 }
const KANBAN_BUDGET_MS = {
  initialDrag: 3000,
  layoutSwitch: 1500,
  secondDrag: 3000,
  diagnostics: 1000,
} as const

/** Collect diagnostic state for isDragging, column highlights, and stuck card classes */
const getDragDiagnostics = async (page: Page, jobId?: string) => {
  return page.evaluate(
    ({ jobId: evaluatedJobId }) => {
      const bodyHasDragClass = document.body.classList.contains('is-dragging')
      const allColumns = document.querySelectorAll('[data-kanban-status]')
      const highlightedColumns: string[] = []
      allColumns.forEach((col) => {
        if (col.classList.contains('bg-blue-50')) {
          highlightedColumns.push(col.getAttribute('data-kanban-status') || 'unknown')
        }
      })

      // Check for stuck SortableJS classes on the dragged card. v2 does not
      // use SortableJS (pragmatic-drag-and-drop instead), so these never
      // appear — this is an absence assertion kept verbatim from v1.
      const stuckCards: { jobId: string; classes: string[] }[] = []
      const sortableClasses = ['sortable-chosen', 'sortable-drag', 'sortable-ghost']
      const selector = evaluatedJobId ? `[data-job-id="${evaluatedJobId}"]` : '.job-card'
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
  // These tests exercise the Office-mode kanban board (status columns + drag-and-drop).
  // Board mode has a device-derived default: narrow viewports — including the tablet
  // viewport these tests resize to — default to Workshop mode, which renders no board
  // at all (just a "select a job" pane). Pin Office mode so a viewport resize swaps the
  // Office grid layout (desktop ⇄ tablet KanbanGridLayout) — the v-if teardown/remount
  // these tests are about — instead of flipping the whole view to Workshop.
  // Same approach as tests/kanban/kanban-mobile.spec.ts.
  test.beforeEach(async ({ authenticatedPage: page }) => {
    await page.addInitScript(() => {
      try {
        window.sessionStorage.setItem('boardMode', 'office')
      } catch {
        // sessionStorage may be unavailable in some contexts
      }
    })
  })

  test('isDragging stuck after drop', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-kanban-status')
    const { column: targetColumn } = await pickTargetColumn(page, sourceStatus)

    // Try to catch the API response, but don't hard-fail if drag was too fast for pragmatic
    let dropCompleted = false
    const reorderResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300,
    )

    await dragCardToColumn(page, jobCard, targetColumn, FAST_DRAG_TIMING)

    // If the reorder never fires, the race below settles via the timeout and
    // leaves reorderResponsePromise pending — attach a no-op catch so that
    // late/never-resolving rejection doesn't surface as an unhandled
    // rejection in a later test.
    reorderResponsePromise.catch(() => {})

    try {
      await Promise.race([
        reorderResponsePromise.then(() => {
          dropCompleted = true
        }),
        page.waitForTimeout(5000),
      ])
    } catch {
      // timeout — drop didn't fire
    }

    log(`Drop completed (API called): ${dropCompleted}`)

    // Wait 3s for any async cleanup / safety timeout to settle
    await page.waitForTimeout(3000)

    // Diagnose drag state — this is the key check regardless of whether drop completed
    const diag = await getDragDiagnostics(page, jobId)
    log('isDragging diagnostics after drop:', JSON.stringify(diag, null, 2))

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

    await expectStepUnder(
      'first drag succeeds on desktop',
      KANBAN_BUDGET_MS.initialDrag,
      async () => {
        const sourceColumn1 = getJobColumn(page, jobId)
        const sourceStatus1 = await sourceColumn1.getAttribute('data-kanban-status')
        const { column: targetColumn1, status: targetStatus1 } = await pickTargetColumn(
          page,
          sourceStatus1,
        )

        const reorderResponse1 = page.waitForResponse(
          (response) =>
            response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
            response.request().method() === 'POST' &&
            response.status() >= 200 &&
            response.status() < 300,
        )

        await dragCardToColumn(page, jobCard, targetColumn1, FAST_DRAG_TIMING)
        await reorderResponse1
        // Exactly one card on the board for this job — guards against a stale
        // drag registration leaving an orphaned DOM node alongside React's
        // re-rendered card after a drop.
        await expect(page.locator(`[data-job-id="${jobId}"]:visible`)).toHaveCount(1, {
          timeout: 15000,
        })
        log(`First drag succeeded: ${sourceStatus1} → ${targetStatus1}`)
      },
    )

    await expectStepUnder('switch to tablet layout', KANBAN_BUDGET_MS.layoutSwitch, async () => {
      log('Switching to tablet viewport...')
      await page.setViewportSize(TABLET_VIEWPORT)
      await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })
    })

    await expectStepUnder(
      'switch back to desktop layout',
      KANBAN_BUDGET_MS.layoutSwitch,
      async () => {
        log('Switching back to desktop viewport...')
        await page.setViewportSize(DESKTOP_VIEWPORT)
        await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })
      },
    )

    const dragSucceeded = await expectStepUnder(
      'second drag succeeds after layout switch',
      KANBAN_BUDGET_MS.secondDrag,
      async () => {
        const jobCard2 = getVisibleJobCard(page, jobId)
        await expect(jobCard2).toBeVisible({ timeout: 15000 })

        const sourceColumn2 = getJobColumn(page, jobId)
        const sourceStatus2 = await sourceColumn2.getAttribute('data-kanban-status')
        const { column: targetColumn2, status: targetStatus2 } = await pickTargetColumn(
          page,
          sourceStatus2,
        )

        const reorderResponse2 = page.waitForResponse(
          (response) =>
            response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
            response.request().method() === 'POST' &&
            response.status() >= 200 &&
            response.status() < 300,
        )

        await dragCardToColumn(page, jobCard2, targetColumn2, FAST_DRAG_TIMING)
        await reorderResponse2
        // Exactly one card for this job in the target column — a stale drag
        // registration after the layout switch would leave an orphaned DOM
        // node here next to React's re-rendered card.
        await expect(
          page.locator(`[data-kanban-status="${targetStatus2}"] [data-job-id="${jobId}"]:visible`),
        ).toHaveCount(1, { timeout: 15000 })
        return true
      },
    ).catch((error: unknown) => {
      console.log('[DEBUG] Second drag FAILED — likely stale drag registration')
      throw error
    })

    log(`Second drag (after layout switch): ${dragSucceeded ? 'PASSED' : 'FAILED'}`)

    const diag = await expectStepUnder(
      'post-layout-switch diagnostics complete quickly',
      KANBAN_BUDGET_MS.diagnostics,
      async () => await getDragDiagnostics(page),
    )
    log('Post-layout-switch diagnostics:', JSON.stringify(diag, null, 2))

    // Check if column containers are connected to DOM
    // Note: :visible is a Playwright pseudo-selector, not valid in native querySelectorAll
    const sortableCheck = await page.evaluate(() => {
      const columns = document.querySelectorAll<HTMLElement>('[data-kanban-status]')
      const results: {
        status: string
        isConnected: boolean
        childCount: number
        visible: boolean
      }[] = []
      columns.forEach((el) => {
        const visible = el.offsetParent !== null || el.getClientRects().length > 0
        results.push({
          status: el.dataset.kanbanStatus || 'unknown',
          isConnected: el.isConnected,
          childCount: el.querySelectorAll('.job-card').length,
          visible,
        })
      })
      return results
    })
    log('Column container check:', JSON.stringify(sortableCheck, null, 2))

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
    log('Starting rapid layout switching...')
    for (let i = 0; i < 5; i++) {
      await page.setViewportSize(TABLET_VIEWPORT)
      await page.waitForTimeout(300)
      await page.setViewportSize(DESKTOP_VIEWPORT)
      await page.waitForTimeout(300)
      log(`Layout switch cycle ${i + 1}/5`)
    }

    // Settle at desktop
    await page.setViewportSize(DESKTOP_VIEWPORT)
    await page.waitForTimeout(2000)

    // Attempt drag-and-drop. Retry a few times: a real regression makes
    // *every* attempt fail; a residual race would just make the first
    // attempt occasionally miss.
    let dragSucceeded = false
    for (let attempt = 1; attempt <= 3 && !dragSucceeded; attempt++) {
      const jobCardAfter = getVisibleJobCard(page, jobId)
      await expect(jobCardAfter).toBeVisible({ timeout: 15000 })

      const sourceColumn = getJobColumn(page, jobId)
      const sourceStatus = await sourceColumn.getAttribute('data-kanban-status')
      const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
        page,
        sourceStatus,
      )

      const reorderResponse = page.waitForResponse(
        (response) =>
          response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
          response.request().method() === 'POST' &&
          response.status() >= 200 &&
          response.status() < 300,
        { timeout: 8000 },
      )

      await dragCardToColumn(page, jobCardAfter, targetColumn, FAST_DRAG_TIMING)

      try {
        await reorderResponse
        await expect(
          page.locator(`[data-kanban-status="${targetStatus}"] [data-job-id="${jobId}"]:visible`),
        ).toHaveCount(1, { timeout: 15000 })
        dragSucceeded = true
      } catch {
        console.log(`[DEBUG] Drag after rapid switching: attempt ${attempt} did not register`)
        await page.waitForTimeout(1000)
      }
    }

    console.log(`[DEBUG] Drag after rapid switching: ${dragSucceeded ? 'PASSED' : 'FAILED'}`)

    await page.waitForTimeout(2000)

    const diag = await getDragDiagnostics(page)
    log('Post-stress-test diagnostics:', JSON.stringify(diag, null, 2))

    expect(dragSucceeded, 'Drag should work after rapid layout switching').toBe(true)
    expect(diag.bodyHasDragClass, 'body should NOT have is-dragging class').toBe(false)
    expect(diag.highlightedColumns.length, 'No columns should be highlighted').toBe(0)
  })
})
