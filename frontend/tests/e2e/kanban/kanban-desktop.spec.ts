import type { Page } from '@playwright/test'

import { getWorkshopStaff } from '../fixtures/api'
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

/**
 * The workshop login, taken off the card first: the shared job is the
 * worker's, so an earlier spec may already have assigned it. Removal of an
 * absent assignment succeeds.
 */
const unassignedWorkshopStaff = async (page: Page, jobId: string): Promise<string> => {
  const staffId = (await getWorkshopStaff(page)).id
  const removed = await page.request.delete(`/api/job/job/${jobId}/assignment/${staffId}`)
  expect(removed.ok(), await removed.text()).toBe(true)
  return staffId
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
    const staffId = await unassignedWorkshopStaff(page, jobId)

    await page.goto('/kanban')
    await expect(page.getByPlaceholder('Search jobs...')).toBeVisible()

    const jobCard = getVisibleJobCard(page, jobId)
    await jobCard.scrollIntoViewIfNeeded()
    await expect(jobCard).toBeVisible({ timeout: 15000 })

    const staffItem = page.locator(`.staff-item[data-staff-id="${staffId}"]`)
    await expect(staffItem).toBeVisible({ timeout: 15000 })
    await expect(jobCard.locator(`[data-staff-id="${staffId}"]`)).toHaveCount(0)

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

    // A search wired to nothing keeps the matching card visible too; the
    // proof is a card that does not match disappearing.
    const otherCard = page.locator(`[data-job-id]:visible:not([data-job-id="${jobId}"])`).first()
    await expect(otherCard).toBeVisible({ timeout: 15000 })
    const otherJobId = await otherCard.getAttribute('data-job-id')

    const searchInput = page.getByPlaceholder('Search jobs...')
    await searchInput.fill(jobNumber)

    await expect(getVisibleJobCard(page, jobId)).toBeVisible({ timeout: 15000 })
    await expect(page.locator(`[data-job-id="${otherJobId}"]:visible`)).toHaveCount(0)
  })
})
