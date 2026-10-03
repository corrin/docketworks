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
  test('a notes edit has one undoable event and restores the original notes', async ({
    authenticatedPage: page,
  }) => {
    const jobUrl = await createTestJob(page, 'Notes History')
    const jobId = getJobIdFromUrl(jobUrl)
    const originalNotes = 'Original notes — keep all of this text, including the final sentence.'
    const updatedNotes = 'Revised notes for the workshop.'
    await autoId(page, 'JobViewTabs-history').click()
    const entries = autoId(page, 'JobHistoryTab-timeline').locator(
      '[data-automation-id^="JobHistoryTab-entry-"]',
    )
    await expect(entries.first()).toBeVisible()
    const initialCount = await entries.count()

    for (const [index, value] of [originalNotes, updatedNotes].entries()) {
      await autoId(page, 'JobViewTabs-jobSettings').click()
      const editor = autoId(page, 'JobSettingsTab-internal-notes').locator('.ql-editor')
      const saved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/job/jobs/${jobId}/` &&
          response.request().method() === 'PATCH',
      )
      await editor.fill(value)
      await editor.blur()
      expect((await saved).status()).toBe(200)
      await autoId(page, 'JobViewTabs-history').click()
      await expect(entries).toHaveCount(initialCount + index + 1)
      await expect(entries.first()).toContainText('Notes Updated')
      await expect(
        entries.first().locator('[data-automation-id^="JobHistoryTab-undo-toggle-"]'),
      ).toHaveCount(1)
    }

    const latest = entries.first()
    await latest.locator('[data-automation-id^="JobHistoryTab-undo-toggle-"]').click()
    await expect(
      latest.locator('[data-automation-id^="JobHistoryTab-undo-before-"]'),
    ).toContainText(originalNotes)
    await expect(latest.locator('[data-automation-id^="JobHistoryTab-undo-after-"]')).toContainText(
      updatedNotes,
    )
    const undone = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/job/jobs/${jobId}/undo-change/` &&
        response.request().method() === 'POST',
    )
    await latest.locator('[data-automation-id^="JobHistoryTab-undo-confirm-"]').click()
    expect((await undone).status()).toBe(200)
    await expect(entries).toHaveCount(initialCount + 3)
    await expect(entries.first()).toContainText('Notes Updated')
    await autoId(page, 'JobViewTabs-jobSettings').click()
    const editor = autoId(page, 'JobSettingsTab-internal-notes').locator('.ql-editor')
    await expect(editor).toHaveText(originalNotes)
    await page.reload()
    await expect(editor).toHaveText(originalNotes)
  })

  test('a delivery-date change has one event and restores its previous date on undo', async ({
    authenticatedPage: page,
  }) => {
    const jobUrl = await createTestJob(page, 'Delivery Date History')
    const jobId = getJobIdFromUrl(jobUrl)
    await autoId(page, 'JobViewTabs-history').click()
    const entries = autoId(page, 'JobHistoryTab-timeline').locator(
      '[data-automation-id^="JobHistoryTab-entry-"]',
    )
    await expect(entries.first()).toBeVisible()
    const initialCount = await entries.count()

    for (const [index, value] of ['2030-10-03', '2030-10-04'].entries()) {
      await autoId(page, 'JobViewTabs-jobSettings').click()
      const dateInput = autoId(page, 'JobSettingsTab-delivery-date')
      const saved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/job/jobs/${jobId}/` &&
          response.request().method() === 'PATCH',
      )
      await dateInput.fill(value)
      await dateInput.blur()
      expect((await saved).status()).toBe(200)
      await autoId(page, 'JobViewTabs-history').click()
      await expect(entries).toHaveCount(initialCount + index + 1)
      await expect(entries.first()).toContainText('Delivery Date Changed')
      await expect(
        entries.first().locator('[data-automation-id^="JobHistoryTab-undo-toggle-"]'),
      ).toHaveCount(1)
    }

    const latest = entries.first()
    await latest.locator('[data-automation-id^="JobHistoryTab-undo-toggle-"]').click()
    await expect(
      latest.locator('[data-automation-id^="JobHistoryTab-undo-before-"]'),
    ).toContainText('2030-10-03')
    await expect(latest.locator('[data-automation-id^="JobHistoryTab-undo-after-"]')).toContainText(
      '2030-10-04',
    )
    const undone = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `/api/job/jobs/${jobId}/undo-change/` &&
        response.request().method() === 'POST',
    )
    await latest.locator('[data-automation-id^="JobHistoryTab-undo-confirm-"]').click()
    expect((await undone).status()).toBe(200)
    await expect(entries).toHaveCount(initialCount + 3)
    await expect(entries.first()).toContainText('Delivery Date Changed')
    await autoId(page, 'JobViewTabs-jobSettings').click()
    await expect(autoId(page, 'JobSettingsTab-delivery-date')).toHaveValue('2030-10-03')
    await page.reload()
    await expect(autoId(page, 'JobSettingsTab-delivery-date')).toHaveValue('2030-10-03')
  })

  test('an event is added and a header change is undone', async ({ authenticatedPage: page }) => {
    // The suffix is all createTestJob needs: it builds `[TEST] Job History
    // <ts>` itself, and passing jobName as well would make the suffix dead.
    // The name the undo has to restore is read off the header below.
    const jobUrl = await createTestJob(page, 'History')
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
    const originalName = (await nameEditor.textContent())?.trim()
    if (!originalName) {
      throw new Error('The job header carries no name to rename')
    }

    await test.step('rename the job from the header', async () => {
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

    await test.step('a status edit records only the status change', async () => {
      await page.reload()
      const entries = autoId(page, 'JobHistoryTab-timeline').locator(
        '[data-automation-id^="JobHistoryTab-entry-"]',
      )
      await expect(entries.first()).toBeVisible()
      const beforeCount = await entries.count()
      await autoId(page, 'JobView-status-display').click()
      await autoId(page, 'JobView-status-select').selectOption('approved')
      const saved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/job/jobs/${jobId}/` &&
          response.request().method() === 'PATCH',
      )
      await autoId(page, 'JobView-status-confirm').click()
      expect((await saved).status()).toBe(200)
      await page.reload()
      await expect(entries).toHaveCount(beforeCount + 1)
      await expect(entries.first()).toContainText('Status Changed')
      await expect(entries.first()).toContainText('Approved')
      await expect(entries.first()).not.toContainText('Priority')
    })
  })
})
