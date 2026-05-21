/**
 * Validates the bug report: dragging a job between kanban columns
 * can cause the card to vanish from the board. The card reappears on
 * page refresh, indicating a frontend cache/rerender issue.
 *
 * Each test asserts the job card is present in exactly one place after
 * the operation — guarding against both vanishing (0 instances) and
 * ghost duplication (2+ instances from stale SortableJS DOM nodes).
 */
import { test, expect } from '../fixtures/auth'
import type { Page, Locator } from '@playwright/test'

const getJobIdFromUrl = (url: string): string => {
  const match = url.match(/\/jobs\/([a-f0-9-]+)/i)
  if (!match) {
    throw new Error(`Unable to parse job id from url: ${url}`)
  }
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

  if (!cardBox || !columnBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }

  const startX = cardBox.x + cardBox.width / 2
  const startY = cardBox.y + cardBox.height / 2
  const endX = columnBox.x + Math.min(60, columnBox.width / 2)
  const endY = columnBox.y + 60

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

const dragCardWithinColumn = async (page: Page, card: Locator, column: Locator) => {
  await card.scrollIntoViewIfNeeded()
  await column.scrollIntoViewIfNeeded()

  const cardBox = await card.boundingBox()
  const columnBox = await column.boundingBox()

  if (!cardBox || !columnBox) {
    throw new Error('Unable to resolve drag and drop positions')
  }

  const startX = cardBox.x + cardBox.width / 2
  const startY = cardBox.y + cardBox.height / 2
  // Drag within the same column — drop near the bottom to trigger reorder
  const endX = columnBox.x + Math.min(60, columnBox.width / 2)
  const endY = columnBox.y + columnBox.height - 60

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

const assertSingleVisibleInstance = async (
  page: Page,
  jobId: string,
  context: string,
) => {
  const allVisibleCards = page.locator(`[data-job-id="${jobId}"]:visible`)
  await expect(allVisibleCards, `${context}: Exactly one visible card for job ${jobId}`).toHaveCount(
    1,
    { timeout: 15000 },
  )
}

const assertJobInColumn = async (page: Page, jobId: string, columnStatus: string) => {
  await expect(
    page.locator(`[data-status="${columnStatus}"] [data-job-id="${jobId}"]:visible`),
    `Job ${jobId} should be visible in column ${columnStatus}`,
  ).toBeVisible({ timeout: 15000 })
}

test.describe('kanban drag vanishing', () => {
  test('search then drag preserves job visibility', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const jobNumberText = (await jobCard.locator('span').first().textContent()) || ''
    const jobNumber = jobNumberText.replace('#', '').trim()
    expect(jobNumber).not.toBe('')

    const searchInput = page.getByPlaceholder('Search jobs...')
    await searchInput.fill(jobNumber)

    await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-status')

    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    const statusResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardToColumn(page, jobCard, targetColumn)
    await statusResponse

    await assertSingleVisibleInstance(page, jobId, 'search then drag')

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

    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-status')

    const { column: targetColumn, status: targetStatus } = await pickTargetColumn(
      page,
      sourceStatus,
    )

    const statusResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardToColumn(page, jobCard, targetColumn)
    await statusResponse

    await assertSingleVisibleInstance(page, jobId, 'cross-column drag')

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

    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    let sourceColumn = getJobColumn(page, jobId)
    const originalStatus = await sourceColumn.getAttribute('data-status')

    const { column: firstTargetColumn, status: firstTargetStatus } = await pickTargetColumn(
      page,
      originalStatus,
    )

    const firstResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardToColumn(page, jobCard, firstTargetColumn)
    await firstResponse

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

    const { column: backTargetColumn } = originalStatus
      ? {
          column: page.locator(`[data-status="${originalStatus}"]:visible`).first(),
          status: originalStatus,
        }
      : await pickTargetColumn(page, intermediateStatus)

    const secondResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardToColumn(page, movedCard, backTargetColumn)
    await secondResponse

    await assertSingleVisibleInstance(page, jobId, 'second drag back')

    if (originalStatus) {
      await assertJobInColumn(page, jobId, originalStatus)
    }

    if (intermediateStatus && intermediateStatus !== originalStatus) {
      await expect(
        page.locator(
          `[data-status="${intermediateStatus}"] [data-job-id="${jobId}"]`,
        ),
      ).toHaveCount(0)
    }
  })

  test('intra-column reorder preserves job visibility', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const sourceColumn = getJobColumn(page, jobId)
    const sourceStatus = await sourceColumn.getAttribute('data-status')

    const reorderResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardWithinColumn(page, jobCard, sourceColumn)

    try {
      await reorderResponse
    } catch {
      // If the reorder API doesn't fire (e.g. drop position is the
      // same), the card should still be visible — the assertion below
      // is the key check.
    }

    await assertSingleVisibleInstance(page, jobId, 'intra-column reorder')

    if (sourceStatus) {
      await assertJobInColumn(page, jobId, sourceStatus)
    }
  })
})
