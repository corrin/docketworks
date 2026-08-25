/**
 * Authored (not ported) walk of the process-forms slice's whole business
 * story through the UI: an office user defines a meeting-minutes form with a
 * real schema, fills it, links a second entry to the first, edits the first
 * entry and reads its audit trail, archives the entry, then archives the
 * form itself. Every seeded title carries [TEST]; no cleanup step needed
 * (e2e_cleanup owns it).
 */
import { z } from 'zod'

import { expect, test } from '../fixtures/auth'
import { autoId, dismissToasts } from '../helpers'

const timestamp = Date.now()
const title = `[TEST] Meeting minutes ${timestamp}`

// The three fields the schema editor's textarea receives verbatim; their
// labels are what the FormDialog preview and the entry history's rendered
// description are asserted against below.
const SCHEMA_TEXT = JSON.stringify(
  {
    fields: [
      { key: 'attendees', label: 'Attendees', type: 'text', required: true },
      { key: 'decisions', label: 'Decisions', type: 'textarea', required: true },
      { key: 'action_items', label: 'Action items', type: 'text', required: true },
    ],
  },
  null,
  2,
)

// EntriesTable's row cells render, in order: one <td> per schema field (3),
// then Date, Staff, Entered by, Links, Actions — see
// frontend/src/features/process/EntriesTable.tsx. With a 3-field schema the
// Links cell is at index 3 (schema) + 3 (Date/Staff/Entered by) = 6.
const LINKS_CELL_INDEX = 3 + 3

const originalAttendees = 'Alice, Bob, Carol'
const originalDecisions = 'Approved the Q3 budget.'
const originalActionItems = 'Send minutes to the team.'
const updatedDecisions = 'Approved the Q3 budget and scheduled a follow-up.'

const linkedAttendees = 'Dave, Erin'
const linkedDecisions = 'Confirmed the follow-up agenda.'
const linkedActionItems = 'Book the follow-up room.'

const createdRecord = z.object({ id: z.string() })

test.describe.serial('form lifecycle', () => {
  test('create, fill, link, audit and archive a form end to end', async ({
    authenticatedPage: page,
  }) => {
    let formId = ''
    let entryId = ''

    await test.step('an office user creates a meeting-minutes form with a real schema', async () => {
      await page.goto('/process-documents/forms/meeting')
      await autoId(page, 'ProcessFormsPage-new-form').click()
      await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'New Form' })).toBeVisible()

      await autoId(page, 'FormDialog-title').fill(title)
      await autoId(page, 'FormDialog-category').selectOption('meeting')
      await autoId(page, 'FormDialog-document-type').selectOption('form')
      await autoId(page, 'FormDialog-schema').fill(SCHEMA_TEXT)

      // The preview renders the real (disabled) EntryForm from the parsed
      // schema before anything is saved.
      const preview = autoId(page, 'FormDialog-preview')
      await expect(preview).toContainText('Attendees')
      await expect(preview).toContainText('Decisions')
      await expect(preview).toContainText('Action items')

      const created = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/process/forms/' &&
          response.request().method() === 'POST' &&
          response.status() === 201,
      )
      await dismissToasts(page)
      await autoId(page, 'FormDialog-submit').click()
      formId = createdRecord.parse(await (await created).json()).id

      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()
      await expect(page.locator('[data-sonner-toast]').first()).toContainText('successfully')
    })

    await test.step('filling the form on its entries page records the first entry', async () => {
      const entriesLoaded = page.waitForResponse(
        (response) =>
          response.url().includes(`/api/process/forms/${formId}/entries/`) &&
          response.request().method() === 'GET' &&
          response.ok(),
      )
      // A real link, same as a person clicking through from the list.
      await page.getByRole('link', { name: title }).click()
      await entriesLoaded
      await expect(autoId(page, 'FormEntries-title')).toHaveText(title)

      await autoId(page, 'EntryForm-field-attendees').fill(originalAttendees)
      await autoId(page, 'EntryForm-field-decisions').fill(originalDecisions)
      await autoId(page, 'EntryForm-field-action_items').fill(originalActionItems)

      const created = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/process/forms/${formId}/entries/` &&
          response.request().method() === 'POST' &&
          response.status() === 201,
      )
      await dismissToasts(page)
      await autoId(page, 'EntryForm-submit').click()
      entryId = createdRecord.parse(await (await created).json()).id

      await expect(page.locator('[data-sonner-toast]').first()).toContainText('Entry saved')
      await expect(autoId(page, `EntriesTable-row-${entryId}`)).toBeVisible()
      await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (1)')
    })

    await test.step("a linked entry on the same form raises the row's links count to 1", async () => {
      await dismissToasts(page)
      await autoId(page, `EntriesTable-links-${entryId}`).click()
      await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
      await expect(autoId(page, 'LinkedEntriesDialog-content')).toBeVisible()
      await expect(autoId(page, 'LinkedEntriesDialog-empty')).toBeVisible()

      // Pick the same form by id: its title is unique, but matching on id
      // sidesteps any ambiguity with other [TEST] forms left by parallel runs.
      await autoId(page, 'LinkedEntriesDialog-add-form').selectOption(formId)

      const linkPrefix = `EntryForm-link-${formId}`
      await autoId(page, `${linkPrefix}-field-attendees`).fill(linkedAttendees)
      await autoId(page, `${linkPrefix}-field-decisions`).fill(linkedDecisions)
      await autoId(page, `${linkPrefix}-field-action_items`).fill(linkedActionItems)

      const linkedCreated = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/process/forms/${formId}/entries/` &&
          response.request().method() === 'POST' &&
          response.status() === 201,
      )
      await autoId(page, `${linkPrefix}-submit`).click()
      await linkedCreated

      await expect(page.locator('[data-sonner-toast]').first()).toContainText('Linked entry saved')
      await expect(page.locator('[data-automation-id^="LinkedEntriesDialog-child-"]')).toHaveCount(
        1,
      )

      await page.keyboard.press('Escape')
      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()

      const linksCell = autoId(page, `EntriesTable-row-${entryId}`)
        .locator('td')
        .nth(LINKS_CELL_INDEX)
      await expect(linksCell).toHaveText('1')
      // The linked entry is a second row of the same form's entries list.
      await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (2)')
    })

    await test.step('editing the entry writes an audit event naming the field and both values', async () => {
      await dismissToasts(page)
      await autoId(page, `EntriesTable-edit-${entryId}`).click()
      await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Edit entry' })).toBeVisible()

      await autoId(page, 'EntryForm-edit-field-decisions').fill(updatedDecisions)

      const updated = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/process/entries/${entryId}/` &&
          response.request().method() === 'PATCH' &&
          response.status() === 200,
      )
      await autoId(page, 'EntryForm-edit-submit').click()
      await updated

      await expect(page.locator('[data-sonner-toast]').first()).toContainText('Entry updated')
      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()

      await dismissToasts(page)
      const history = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/process/entries/${entryId}/history/` &&
          response.request().method() === 'GET' &&
          response.ok(),
      )
      await autoId(page, `EntriesTable-history-${entryId}`).click()
      await history

      await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
      await expect(autoId(page, 'EntryHistoryDialog-content')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Entry history' })).toBeVisible()

      // Newest first: the edit's event, then the original entry_created.
      const events = page.locator('[data-automation-id^="EntryHistoryDialog-event-"]')
      await expect(events).toHaveCount(2)
      await expect(events.nth(0)).toContainText('Decisions')
      await expect(events.nth(0)).toContainText(originalDecisions)
      await expect(events.nth(0)).toContainText(updatedDecisions)
      await expect(events.nth(1)).toContainText('Entry created')

      await page.keyboard.press('Escape')
      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()
    })

    await test.step('archiving the entry leaves only the linked child in the count', async () => {
      await dismissToasts(page)
      const archived = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/process/entries/${entryId}/` &&
          response.request().method() === 'DELETE' &&
          response.status() === 204,
      )
      page.once('dialog', (dialog) => void dialog.accept())
      await autoId(page, `EntriesTable-archive-${entryId}`).click()
      await archived

      await expect(page.locator('[data-sonner-toast]').first()).toContainText('Entry archived')
      // Only the linked child (never archived) remains active on this form.
      await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (1)')
    })

    await test.step('archiving the form drops it from the default list and keeps it under Show archived', async () => {
      await dismissToasts(page)
      const listLoaded = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/process/forms/' &&
          response.request().method() === 'GET' &&
          response.ok(),
      )
      await page.goto('/process-documents/forms/meeting')
      await listLoaded

      await autoId(page, `ProcessFormsPage-edit-${formId}`).click()
      await expect(page.locator('[data-slot="dialog-content"]')).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Edit Form' })).toBeVisible()

      await autoId(page, 'FormDialog-archived').check()

      const patched = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `/api/process/forms/${formId}/` &&
          response.request().method() === 'PATCH' &&
          response.status() === 200,
      )
      await autoId(page, 'FormDialog-submit').click()
      await patched

      await expect(page.locator('[data-slot="dialog-content"]')).toBeHidden()
      await expect(page.locator('[data-sonner-toast]').first()).toContainText('successfully')
      await expect(autoId(page, `ProcessFormsPage-row-${formId}`)).toHaveCount(0)

      const archivedListLoaded = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/process/forms/' &&
          response.request().method() === 'GET' &&
          new URL(response.url()).searchParams.get('status') === 'archived' &&
          response.ok(),
      )
      await autoId(page, 'ProcessFormsPage-show-archived').check()
      await archivedListLoaded

      await expect(autoId(page, `ProcessFormsPage-row-${formId}`)).toBeVisible()
    })
  })
})
