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

  // Native HTML5 DnD requires deliberate timing:
  // 1. Hold after mousedown so the browser initiates native drag
  // 2. Move in steps so drag events fire on intermediate elements
  // 3. Brief settle after release for SortableJS to process the drop
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

const pickAssignableStaff = async (card: Locator, staffItems: Locator) => {
  const assignedIds = new Set(
    await card
      .locator('[data-staff-id]')
      .evaluateAll((nodes) =>
        nodes
          .map((node) => node.getAttribute('data-staff-id'))
          .filter((value): value is string => Boolean(value)),
      ),
  )

  const staffCount = await staffItems.count()
  for (let i = 0; i < staffCount; i += 1) {
    const candidate = staffItems.nth(i)
    const staffId = await candidate.getAttribute('data-staff-id')
    if (staffId && !assignedIds.has(staffId)) {
      return { staffItem: candidate, staffId }
    }
  }

  throw new Error('No available staff to assign in Kanban staff panel')
}

test.describe.serial('kanban desktop', () => {
  test('change status via drag and drop', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
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
        response.url().includes(`/job/api/jobs/${jobId}/update-status/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardToColumn(page, jobCard, targetColumn)
    await statusResponse

    await expect(
      page.locator(`[data-status="${targetStatus}"] [data-job-id="${jobId}"]:visible`),
    ).toBeVisible({ timeout: 15000 })
  })

  test('assign staff to job card via drag', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto('/kanban')
    await page.waitForLoadState('networkidle')

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const staffItems = page.locator('.staff-item')
    await expect(staffItems.first()).toBeVisible({ timeout: 15000 })

    const { staffItem, staffId } = await pickAssignableStaff(jobCard, staffItems)

    const assignResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/job/api/job/${jobId}/assignment`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await staffItem.dragTo(jobCard, { force: true })
    await assignResponse

    await expect(jobCard.locator(`[data-staff-id="${staffId}"]`)).toHaveCount(1)
  })

  test('search filters kanban jobs', async ({ authenticatedPage: page, sharedEditJobUrl }) => {
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
  })
})
