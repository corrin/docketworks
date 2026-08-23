import { test, expect } from '../fixtures/auth'
import { autoId, createTestJob, getJobIdFromUrl } from '../helpers'

/**
 * The job History tab: a manually added event reaches the timeline, and a
 * header edit recorded as a delta is undone from the entry it produced —
 * with the header showing the previous value again without a page reload
 * (v1 called window.location.reload() there; v2 invalidates the job query).
 *
 * The job is created fresh rather than shared: both halves write to the
 * job's own history, and a shared job would carry whatever the previous
 * spec left on its timeline.
 */
test.describe('job history', () => {
  test('an event is added and a header change is undone', async ({ authenticatedPage: page }) => {
    const originalName = `[TEST] Job History ${Date.now()}`
    const jobUrl = await createTestJob(page, 'History', { jobName: originalName })
    const jobId = getJobIdFromUrl(jobUrl)

    await autoId(page, 'JobViewTabs-history').click()

    const eventDescription = `[TEST] History event ${Date.now()}`
    await test.step('add an event', async () => {
      await autoId(page, 'JobHistoryTab-add-event-toggle').click()
      await autoId(page, 'JobHistoryTab-event-description').fill(eventDescription)

      const created = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/job/jobs/${jobId}/events/create/` &&
          response.request().method() === 'POST' &&
          response.status() === 201,
      )
      await autoId(page, 'JobHistoryTab-add-event-submit').click()
      await created

      // Newest first, so the event just written heads the list.
      const entries = autoId(page, 'JobHistoryTab-timeline').locator(
        '[data-automation-id^="JobHistoryTab-entry-"]',
      )
      await expect(entries.first()).toContainText(eventDescription)
    })

    const nameEditor = autoId(page, 'JobView-job-number').locator('..').locator('.inline-edit-text')
    const renamedTo = `[TEST] Job Renamed ${Date.now()}`

    await test.step('rename the job from the header', async () => {
      await expect(nameEditor).toContainText(originalName)
      await nameEditor.click()
      const nameInput = nameEditor.locator('input')
      await nameInput.fill(renamedTo)

      const saved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/job/jobs/${jobId}/` &&
          response.request().method() === 'PATCH' &&
          response.status() === 200,
      )
      await nameInput.press('Enter')
      await saved
      await expect(nameEditor).toContainText(renamedTo)
    })

    await test.step('undo the rename from its timeline entry', async () => {
      // The rename is now the newest entry, and the only undoable one on this
      // job: manual events carry no delta, so they offer no undo control.
      const undoToggle = page.locator('[data-automation-id^="JobHistoryTab-undo-toggle-"]').first()
      await expect(undoToggle).toBeVisible()
      const toggleId = await undoToggle.getAttribute('data-automation-id')
      if (toggleId === null) {
        throw new Error('The undo toggle lost the automation id it was located by')
      }
      const entryId = toggleId.replace('JobHistoryTab-undo-toggle-', '')

      await undoToggle.click()
      await expect(autoId(page, `JobHistoryTab-undo-before-${entryId}`)).toContainText(originalName)
      await expect(autoId(page, `JobHistoryTab-undo-after-${entryId}`)).toContainText(renamedTo)

      const undone = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/job/jobs/${jobId}/undo-change/` &&
          response.request().method() === 'POST' &&
          response.status() === 200,
      )
      await autoId(page, `JobHistoryTab-undo-confirm-${entryId}`).click()
      await undone

      // No page.reload(): the undo invalidates the job detail the header reads.
      await expect(nameEditor).toContainText(originalName)
    })
  })
})
