/** Shared setup for the kanban drag-and-drop cluster (one implementation per concept). */
import type { Locator, Page } from '@playwright/test'

/** Visible kanban job card for `jobId`. */
export const getVisibleJobCard = (page: Page, jobId: string): Locator =>
  page.locator(`[data-job-id="${jobId}"]:visible`).first()

export const getVisibleColumns = (page: Page): Locator =>
  page.locator('[data-kanban-status]:visible')

export const getJobColumn = (page: Page, jobId: string): Locator =>
  getVisibleColumns(page)
    .filter({ has: getVisibleJobCard(page, jobId) })
    .first()

export const pickTargetColumn = async (
  page: Page,
  currentStatus: string | null,
): Promise<{ column: Locator; status: string }> => {
  const preferredStatus = 'in_progress'
  if (currentStatus !== preferredStatus) {
    const preferredColumn = page.locator(`[data-kanban-status="${preferredStatus}"]:visible`)
    if (await preferredColumn.count()) {
      return { column: preferredColumn.first(), status: preferredStatus }
    }
  }

  const columns = getVisibleColumns(page)
  const columnCount = await columns.count()

  for (let i = 0; i < columnCount; i += 1) {
    const column = columns.nth(i)
    const status = await column.getAttribute('data-kanban-status')
    if (status && status !== currentStatus) {
      return { column, status }
    }
  }

  throw new Error('Unable to find target column for status change')
}

/**
 * Mouse choreography timing for a drag gesture. Deliberately different per
 * spec — debug-drag-bugs stress-tests a fast interaction, the others use the
 * v1-identical slow profile — so callers pass their own constant rather than
 * this module picking one number for everyone.
 */
export interface DragTiming {
  holdMs: number
  steps: number
  stepDelayMs: number
  settleMs: number
}

/** The v1-identical slow profile: shared by kanban-desktop and kanban-drag-vanishing. */
export const STANDARD_DRAG_TIMING: DragTiming = {
  holdMs: 200,
  steps: 25,
  stepDelayMs: 20,
  settleMs: 500,
}

/** The fast profile debug-drag-bugs uses to stress rapid interaction. */
export const FAST_DRAG_TIMING: DragTiming = {
  holdMs: 150,
  steps: 8,
  stepDelayMs: 8,
  settleMs: 300,
}

/**
 * The mouse-sequence core: hold after mousedown so the browser initiates the
 * drag, move in steps so drag events fire on intermediate elements, brief
 * settle after release so the drop is processed. Takes a raw endpoint (not
 * just a column box) so callers can target either a column or another card's
 * edge for an intra-column reorder.
 */
export const dragMouseSequence = async (
  page: Page,
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  timing: DragTiming,
): Promise<void> => {
  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.waitForTimeout(timing.holdMs)

  for (let i = 1; i <= timing.steps; i++) {
    const t = i / timing.steps
    await page.mouse.move(startX + (endX - startX) * t, startY + (endY - startY) * t)
    await page.waitForTimeout(timing.stepDelayMs)
  }

  await page.mouse.up()
  await page.waitForTimeout(timing.settleMs)
}

export const dragCardToColumn = async (
  page: Page,
  card: Locator,
  column: Locator,
  timing: DragTiming,
): Promise<void> => {
  await card.scrollIntoViewIfNeeded()
  await column.scrollIntoViewIfNeeded()

  const cardBox = await card.boundingBox()
  const columnBox = await column.boundingBox()

  if (!cardBox || !columnBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }

  const startX = cardBox.x + cardBox.width / 2
  const startY = cardBox.y + cardBox.height / 2
  const endX = columnBox.x + Math.min(60, columnBox.width / 2)
  const endY = columnBox.y + 60

  await dragMouseSequence(page, startX, startY, endX, endY, timing)
}

export const captureDragConsoleIssues = (page: Page): string[] => {
  const issues: string[] = []
  page.on('console', (message) => {
    if (!['error', 'warning'].includes(message.type())) {
      return
    }
    const text = message.text()
    // React 19 dropped the 'Warning:' prefix — dev-mode warnings now arrive
    // as unprefixed console.error, which the auth fixture already fails the
    // suite on. This only needs to catch what that fixture-wide guard can't:
    // an explicit unhandled-error log.
    if (text.includes('Unhandled error')) {
      issues.push(text)
    }
  })
  page.on('pageerror', (error) => {
    issues.push(error.message)
  })
  return issues
}
