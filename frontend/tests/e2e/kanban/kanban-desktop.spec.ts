import type { Locator } from '@playwright/test'

import { expect, test } from '../fixtures/auth'
import { getJobIdFromUrl } from '../helpers'
import {
  captureDragConsoleIssues,
  dragCardToColumn,
  getJobColumn,
  getVisibleJobCard,
  pickTargetColumn,
  STANDARD_DRAG_TIMING,
} from './support'

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
    const consoleIssues = captureDragConsoleIssues(page)

    await page.goto('/kanban')
    // The board holds a live SSE connection, so networkidle never fires
    // here by design; wait for the board itself to render instead.
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

    const reorderResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/jobs/${jobId}/reorder/`) &&
        response.request().method() === 'POST' &&
        response.status() >= 200 &&
        response.status() < 300
      )
    })

    await dragCardToColumn(page, jobCard, targetColumn, STANDARD_DRAG_TIMING)
    await reorderResponse

    await expect(
      page.locator(`[data-kanban-status="${targetStatus}"] [data-job-id="${jobId}"]:visible`),
    ).toBeVisible({ timeout: 15000 })
    expect(consoleIssues).toEqual([])
  })

  test('assign staff to job card via drag', async ({
    authenticatedPage: page,
    sharedEditJobUrl,
  }) => {
    const jobId = getJobIdFromUrl(sharedEditJobUrl)

    await page.goto('/kanban')
    await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const staffItems = page.locator('.staff-item')
    await expect(staffItems.first()).toBeVisible({ timeout: 15000 })

    const { staffItem, staffId } = await pickAssignableStaff(jobCard, staffItems)

    const assignResponse = page.waitForResponse((response) => {
      return (
        response.url().includes(`/api/job/job/${jobId}/assignment`) &&
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
    await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

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
