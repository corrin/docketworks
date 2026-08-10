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

/**
 * The verbatim v1 mouse choreography (200ms hold, 25 steps at 20ms, 500ms
 * settle), factored to take a raw endpoint instead of only a column box —
 * pragmatic (unlike v1's SortableJS) resolves a drop from whatever DOM
 * element sits under the pointer, so a within-column reorder needs to land
 * the pointer on a specific card's edge, not just "somewhere in the column"
 * (Task 0 spike finding; see task-0-report.md). dragCardToColumn below is
 * the v1-identical column-targeted wrapper; dragCardWithinColumn is the new
 * card-edge-targeted caller this generalisation exists for.
 */
const dragCardTo = async (page: Page, card: Locator, endX: number, endY: number) => {
  await card.scrollIntoViewIfNeeded()

  const cardBox = await card.boundingBox()
  if (!cardBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }

  const startX = cardBox.x + cardBox.width / 2
  const startY = cardBox.y + cardBox.height / 2

  await page.mouse.move(startX, startY)
  await page.mouse.down()
  await page.waitForTimeout(200)

  const steps = 25
  const stepDelay = 20
  for (let i = 1; i <= steps; i++) {
    const t = i / steps
    await page.mouse.move(startX + (endX - startX) * t, startY + (endY - startY) * t)
    await page.waitForTimeout(stepDelay)
  }

  await page.mouse.up()
  await page.waitForTimeout(500)
}

const dragCardToColumn = async (page: Page, card: Locator, column: Locator) => {
  await column.scrollIntoViewIfNeeded()
  const columnBox = await column.boundingBox()
  if (!columnBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }
  await dragCardTo(page, card, columnBox.x + Math.min(60, columnBox.width / 2), columnBox.y + 60)
}

/**
 * Drags `card` onto the bottom edge of `targetCard` — a different, visible
 * card already in the same column — so the drop lands on the target card's
 * own drop target and resolves to an explicit anchor+placement reorder,
 * exercising the within-column path deterministically regardless of column
 * scroll height or card count.
 */
const dragCardWithinColumn = async (page: Page, card: Locator, targetCard: Locator) => {
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

/** Another visible card in `column`, biased to the last one — the within-column drop target. */
const pickWithinColumnTarget = async (column: Locator, jobId: string): Promise<Locator> => {
  const others = column.locator(`[data-job-id]:visible:not([data-job-id="${jobId}"])`)
  const count = await others.count()
  if (count === 0) {
    throw new Error(`No other visible card in the column to reorder job ${jobId} against`)
  }
  return others.last()
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
    page.locator(`[data-status="${columnStatus}"] [data-job-id="${jobId}"]:visible`),
    `Job ${jobId} should be visible in column ${columnStatus}`,
  ).toBeVisible({ timeout: 15000 })
}

const captureDragConsoleIssues = (page: Page): string[] => {
  const issues: string[] = []
  page.on('console', (message) => {
    if (!['error', 'warning'].includes(message.type())) {
      return
    }
    const text = message.text()
    // v1 watched for '[Vue warn]'; React's equivalent framework complaint is a
    // 'Warning:'-prefixed console message. Either way this is an absence
    // assertion: a drag must not make the framework unhappy.
    if (text.includes('Warning:') || text.includes('Unhandled error')) {
      issues.push(text)
    }
  })
  page.on('pageerror', (error) => {
    issues.push(error.message)
  })
  return issues
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
    const sourceStatus = await sourceColumn.getAttribute('data-status')

    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    // Guards: a backend regression that fails the reorder save (non-2xx)
    // or a frontend regression that stops emitting it must fail here with
    // the real status and body, not as a timeout or a vanished card below.
    await expectReorderSuccess(page, jobId, () => dragCardToColumn(page, jobCard, targetColumn))

    await assertSingleVisibleInstance(page, jobId, 'search then drag')
    expect(consoleIssues).toEqual([])

    await assertJobInColumn(page, jobId, targetStatus)

    if (sourceStatus) {
      await expect(
        page.locator(`[data-status="${sourceStatus}"] [data-job-id="${jobId}"]`),
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
    const sourceStatus = await sourceColumn.getAttribute('data-status')

    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    // Guards: a cross-column drag whose reorder save fails (non-2xx) or
    // never fires must fail here with the real status and body, not as a
    // timeout or a vanished card below.
    await expectReorderSuccess(page, jobId, () => dragCardToColumn(page, jobCard, targetColumn))

    await assertSingleVisibleInstance(page, jobId, 'cross-column drag')
    expect(consoleIssues).toEqual([])

    await assertJobInColumn(page, jobId, targetStatus)

    if (sourceStatus) {
      await expect(
        page.locator(`[data-status="${sourceStatus}"] [data-job-id="${jobId}"]`),
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
    const originalStatus = await sourceColumn.getAttribute('data-status')

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
      dragCardToColumn(page, jobCard, firstTargetColumn),
    )

    await assertSingleVisibleInstance(page, jobId, 'first drag')

    await assertJobInColumn(page, jobId, firstTargetStatus)

    if (originalStatus) {
      await expect(
        page.locator(`[data-status="${originalStatus}"] [data-job-id="${jobId}"]`),
      ).toHaveCount(0)
    }

    const movedCard = getVisibleJobCard(page, jobId)

    sourceColumn = getJobColumn(page, jobId)
    const intermediateStatus = await sourceColumn.getAttribute('data-status')

    // Only `column` is ever used from this branch — the ternary's true arm
    // is left column-only (rather than mirroring pickTargetColumn's
    // {column, status} shape) because TS's excess-property check against the
    // destructuring target's inferred {column} shape rejects the extra
    // `status` field otherwise.
    const backTargetColumn: Locator = originalStatus
      ? page.locator(`[data-status="${originalStatus}"]:visible`).first()
      : (await pickTargetColumn(page, intermediateStatus)).column

    // Guards: the second (return) drag's reorder save failing or being
    // dropped after a just-settled first save — the rapid-sequential case
    // that historically made cards vanish — must fail with the real status.
    await expectReorderSuccess(page, jobId, () =>
      dragCardToColumn(page, movedCard, backTargetColumn),
    )

    await assertSingleVisibleInstance(page, jobId, 'second drag back')
    expect(consoleIssues).toEqual([])

    if (originalStatus) {
      await assertJobInColumn(page, jobId, originalStatus)
    }

    if (intermediateStatus && intermediateStatus !== originalStatus) {
      await expect(
        page.locator(`[data-status="${intermediateStatus}"] [data-job-id="${jobId}"]`),
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
    const sourceStatus = await sourceColumn.getAttribute('data-status')
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
