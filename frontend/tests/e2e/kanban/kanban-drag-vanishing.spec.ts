/**
 * Validates the bug report: dragging a job between kanban columns
 * can cause the card to vanish from the board. The card reappears on
 * page refresh, indicating a frontend cache/rerender issue.
 *
 * Each test asserts the job card is present in exactly one place after
 * the operation — guarding against both vanishing (0 instances) and
 * ghost duplication (2+ instances from a stale drag-registration DOM node).
 */
import type { Locator, Page, Response } from '@playwright/test'

import { expect, test } from '../fixtures/auth'
import { autoId, getJobIdFromUrl } from '../helpers'
import {
  captureDragConsoleIssues,
  dragCardToColumn,
  dragMouseSequence,
  getJobColumn,
  getVisibleJobCard,
  pickTargetColumn,
  STANDARD_DRAG_TIMING,
} from './support'

/**
 * Drags `card` onto a raw endpoint. Unlike dragCardToColumn (shared, targets
 * a column), this is the card-edge-targeted primitive dragCardWithinColumn
 * needs: pragmatic (unlike v1's SortableJS) resolves a drop from whatever DOM
 * element sits under the pointer, so a within-column reorder must land the
 * pointer on a specific card's edge, not just "somewhere in the column"
 * (Task 0 spike finding; see task-0-report.md).
 */
const dragCardTo = async (page: Page, card: Locator, endX: number, endY: number) => {
  await card.scrollIntoViewIfNeeded()

  const cardBox = await card.boundingBox()
  if (!cardBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }

  const startX = cardBox.x + cardBox.width / 2
  const startY = cardBox.y + cardBox.height / 2

  await dragMouseSequence(page, startX, startY, endX, endY, STANDARD_DRAG_TIMING)
}

/**
 * Drags `card` onto the bottom edge of `targetCard` — a different, visible
 * card already in the same column — so the drop lands on the target card's
 * own drop target and resolves to an explicit anchor+placement reorder,
 * exercising the within-column path deterministically regardless of column
 * scroll height or card count.
 *
 * Scrolls the DRAGGED card into view FIRST, then the target, THEN measures
 * the target's box — not the other order. Both cards share one 90vh
 * overflow scroller, and dragCardTo's own first act is another
 * `card.scrollIntoViewIfNeeded()`; measuring targetBox before that scroll
 * (the original order) captures coordinates that call can then invalidate,
 * sending the pointer to a stale position — pickWithinColumnTarget below
 * keeps the two cards adjacent so this second scroll is a no-op, but the
 * ordering here is the actual guarantee, independent of that.
 */
const dragCardWithinColumn = async (page: Page, card: Locator, targetCard: Locator) => {
  await card.scrollIntoViewIfNeeded()
  await targetCard.scrollIntoViewIfNeeded()
  const targetBox = await targetCard.boundingBox()
  if (!targetBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }
  await dragCardTo(
    page,
    card,
    targetBox.x + targetBox.width / 2,
    targetBox.y + targetBox.height - 4,
  )
}

/**
 * The card immediately adjacent to `jobId` in DOM order (next, or previous
 * if the dragged card is last) — not just "some other visible card".
 * Playwright's `:visible` is CSS visibility, not scroll-viewport
 * intersection: in a column taller than the 90vh scroller, an arbitrary
 * other card (e.g. the column's last one in DOM order, the previous
 * selection here) can sit far from wherever the dragged card scrolls into
 * view, forcing the two scrollIntoViewIfNeeded calls in dragCardWithinColumn
 * to fight over the scroll position — the drag would then run against
 * pre-scroll coordinates, landing on the wrong card, in blank space (a
 * silent no-op when the resolved anchor is the source card itself), or
 * hanging expectReorderSuccess to its timeout. An adjacent card is always in
 * the same scroll neighbourhood as the dragged card.
 */
const pickWithinColumnTarget = async (column: Locator, jobId: string): Promise<Locator> => {
  const cards = column.locator('[data-job-id]:visible')
  const ids = await cards.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('data-job-id')),
  )
  const sourceIndex = ids.indexOf(jobId)
  if (sourceIndex === -1) {
    throw new Error(`Job ${jobId} not found among visible cards in its own column`)
  }
  const targetIndex = sourceIndex + 1 < ids.length ? sourceIndex + 1 : sourceIndex - 1
  if (targetIndex < 0) {
    throw new Error(`No other visible card in the column to reorder job ${jobId} against`)
  }
  return cards.nth(targetIndex)
}

/**
 * Performs a drag and asserts the POST /reorder/ request it triggers
 * succeeded. The response wait matches URL + method only — never status.
 * A status-filtered predicate can never match a real backend failure
 * (e.g. a 503), so the failure would surface as a misleading 30s timeout
 * instead of the actual status and body. The wait is started BEFORE the
 * drag so a fast response cannot slip past the listener.
 */
const expectReorderSuccess = async (
  page: Page,
  jobId: string,
  performDrag: () => Promise<void>,
): Promise<Response> => {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
      response.request().method() === 'POST',
  )

  await performDrag()

  const response = await responsePromise
  if (!response.ok()) {
    const body = await response.text()
    throw new Error(`reorder failed: ${response.status()} ${body}`)
  }
  return response
}

const assertSingleVisibleInstance = async (page: Page, jobId: string, context: string) => {
  const allVisibleCards = page.locator(`[data-job-id="${jobId}"]:visible`)
  await expect(
    allVisibleCards,
    `${context}: Exactly one visible card for job ${jobId}`,
  ).toHaveCount(1, { timeout: 15000 })
}

const assertJobInColumn = async (page: Page, jobId: string, columnStatus: string) => {
  await expect(
    page.locator(`[data-kanban-status="${columnStatus}"] [data-job-id="${jobId}"]:visible`),
    `Job ${jobId} should be visible in column ${columnStatus}`,
  ).toBeVisible({ timeout: 15000 })
}

test.describe('kanban drag vanishing', () => {
  test('search then drag preserves job visibility', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    // The fixture exposes only the job URL, so read the job number from the
    // job page header (same source as tests/timesheet/keyboard-nav.spec.ts).
    // Do NOT scrape it from the unfiltered board: kanban columns are capped
    // (200 cards per column), so on production-size databases the shared
    // job's card can legitimately be absent until the search below filters
    // the board.
    await page.goto(sharedEditJobUrl)
    const jobNumberLocator = autoId(page, 'JobView-job-number').first()
    await expect(jobNumberLocator).toContainText(/\d+/)
    const jobNumberText = await jobNumberLocator.innerText()
    const jobNumber = jobNumberText.match(/#(\d+)/)?.[1] ?? ''
    expect(jobNumber).not.toBe('')

    // Attach the console capture only now, keeping it scoped to the kanban
    // drag flow it was written for.
    const consoleIssues = captureDragConsoleIssues(page)

    await page.goto('/kanban')

    const searchInput = page.getByPlaceholder('Search jobs...')
    await expect(searchInput).toBeVisible()
    await searchInput.fill(jobNumber)

    await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })

    const jobCard = getVisibleJobCard(page, jobId)
    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-kanban-status')

    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    // Guards: a backend regression that fails the reorder save (non-2xx)
    // or a frontend regression that stops emitting it must fail here with
    // the real status and body, not as a timeout or a vanished card below.
    await expectReorderSuccess(page, jobId, () =>
      dragCardToColumn(page, jobCard, targetColumn, STANDARD_DRAG_TIMING),
    )

    await assertSingleVisibleInstance(page, jobId, 'search then drag')
    expect(consoleIssues).toEqual([])

    await assertJobInColumn(page, jobId, targetStatus)

    if (sourceStatus) {
      await expect(
        page.locator(`[data-kanban-status="${sourceStatus}"] [data-job-id="${jobId}"]`),
        `Job ${jobId} should no longer be in source column ${sourceStatus}`,
      ).toHaveCount(0)
    }
  })

  test('cross-column drag preserves job visibility', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)
    const consoleIssues = captureDragConsoleIssues(page)

    await page.goto('/kanban')
    await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-kanban-status')

    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    // Guards: a cross-column drag whose reorder save fails (non-2xx) or
    // never fires must fail here with the real status and body, not as a
    // timeout or a vanished card below.
    await expectReorderSuccess(page, jobId, () =>
      dragCardToColumn(page, jobCard, targetColumn, STANDARD_DRAG_TIMING),
    )

    await assertSingleVisibleInstance(page, jobId, 'cross-column drag')
    expect(consoleIssues).toEqual([])

    await assertJobInColumn(page, jobId, targetStatus)

    if (sourceStatus) {
      await expect(
        page.locator(`[data-kanban-status="${sourceStatus}"] [data-job-id="${jobId}"]`),
        `Job ${jobId} should no longer be in source column ${sourceStatus}`,
      ).toHaveCount(0)
    }
  })

  test('rapid sequential drag back to original column', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)
    const consoleIssues = captureDragConsoleIssues(page)

    await page.goto('/kanban')
    await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    let sourceColumn = getJobColumn(page, jobId)
    const originalStatus = await sourceColumn.getAttribute('data-kanban-status')

    const { column: firstTargetColumn, status: firstTargetStatus } = await pickTargetColumn(
      page,
      originalStatus,
    )

    // Drag persistence is serialized: a second drag must not start until the
    // first save has settled. Awaiting AND asserting the first reorder
    // response before the second drag guards two regressions — overlapping
    // in-flight reorders being allowed again, and a non-2xx first response
    // being masked as a timeout instead of reported with status and body.
    await expectReorderSuccess(page, jobId, () =>
      dragCardToColumn(page, jobCard, firstTargetColumn, STANDARD_DRAG_TIMING),
    )

    await assertSingleVisibleInstance(page, jobId, 'first drag')

    await assertJobInColumn(page, jobId, firstTargetStatus)

    if (originalStatus) {
      await expect(
        page.locator(`[data-kanban-status="${originalStatus}"] [data-job-id="${jobId}"]`),
      ).toHaveCount(0)
    }

    const movedCard = getVisibleJobCard(page, jobId)

    sourceColumn = getJobColumn(page, jobId)
    const intermediateStatus = await sourceColumn.getAttribute('data-kanban-status')

    // Only `column` is ever used from this branch — the ternary's true arm
    // is left column-only (rather than mirroring pickTargetColumn's
    // {column, status} shape) because TS's excess-property check against the
    // destructuring target's inferred {column} shape rejects the extra
    // `status` field otherwise.
    const backTargetColumn: Locator = originalStatus
      ? page.locator(`[data-kanban-status="${originalStatus}"]:visible`).first()
      : (await pickTargetColumn(page, intermediateStatus)).column

    // Guards: the second (return) drag's reorder save failing or being
    // dropped after a just-settled first save — the rapid-sequential case
    // that historically made cards vanish — must fail with the real status.
    await expectReorderSuccess(page, jobId, () =>
      dragCardToColumn(page, movedCard, backTargetColumn, STANDARD_DRAG_TIMING),
    )

    await assertSingleVisibleInstance(page, jobId, 'second drag back')
    expect(consoleIssues).toEqual([])

    if (originalStatus) {
      await assertJobInColumn(page, jobId, originalStatus)
    }

    if (intermediateStatus && intermediateStatus !== originalStatus) {
      await expect(
        page.locator(`[data-kanban-status="${intermediateStatus}"] [data-job-id="${jobId}"]`),
      ).toHaveCount(0)
    }
  })

  test('intra-column reorder preserves job visibility', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)
    const consoleIssues = captureDragConsoleIssues(page)

    await page.goto('/kanban')
    await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-kanban-status')
    const targetCard = await pickWithinColumnTarget(sourceColumn, jobId)

    // Guards: an intra-column drop that stops emitting a reorder request,
    // or whose save fails (non-2xx), must fail loudly here with the real
    // status and body — not be swallowed as a tolerated timeout while the
    // visibility assertion below happens to pass.
    await expectReorderSuccess(page, jobId, () => dragCardWithinColumn(page, jobCard, targetCard))

    await assertSingleVisibleInstance(page, jobId, 'intra-column reorder')
    expect(consoleIssues).toEqual([])

    if (sourceStatus) {
      await assertJobInColumn(page, jobId, sourceStatus)
    }
  })
})
