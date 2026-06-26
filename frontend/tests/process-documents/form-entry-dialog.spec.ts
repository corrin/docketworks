import { expect, type APIResponse } from '@playwright/test'
import { test } from '../fixtures/auth'
import { autoId } from '../fixtures/helpers'

type FormField = {
  key: string
  label: string
  type: 'text' | 'textarea' | 'date'
  required?: boolean
}

type FormResponse = {
  id: string
  title: string
}

type FormEntryResponse = {
  id: string
}

const TALL_FORM_FIELDS: FormField[] = [
  { key: 'incident_date', label: 'Incident Date', type: 'date', required: true },
  { key: 'location', label: 'Location', type: 'text' },
  { key: 'description', label: 'Description', type: 'textarea' },
  { key: 'persons_involved', label: 'Persons Involved', type: 'textarea' },
  { key: 'immediate_cause', label: 'Immediate Cause', type: 'textarea' },
  { key: 'root_cause', label: 'Root Cause', type: 'textarea' },
  { key: 'corrective_actions', label: 'Corrective Actions', type: 'textarea' },
  { key: 'follow_up_notes', label: 'Follow-up Notes', type: 'textarea' },
  { key: 'completed_by', label: 'Completed By', type: 'text' },
  { key: 'review_date', label: 'Review Date', type: 'date' },
]

async function expectJsonResponse<T>(response: APIResponse, context: string): Promise<T> {
  const responseText = await response.text()
  expect(response.ok(), `${context}: ${response.status()} ${responseText}`).toBeTruthy()
  return JSON.parse(responseText) as T
}

function entryData(): Record<string, string> {
  return Object.fromEntries(
    TALL_FORM_FIELDS.map((field) => {
      if (field.type === 'date') {
        return [field.key, '2026-06-27']
      }
      return [field.key, `${field.label} test value`]
    }),
  )
}

test('tall form entry edit dialog stays within viewport and scrolls to actions', async ({
  authenticatedPage: page,
}) => {
  await page.setViewportSize({ width: 390, height: 640 })

  const title = `[TEST] Tall Incident Form ${Date.now()}`
  const form = await expectJsonResponse<FormResponse>(
    await page.request.post('/api/process/forms/incident/', {
      headers: { Accept: 'application/json' },
      data: {
        title,
        document_number: `KAN-160-${Date.now()}`,
        tags: ['incident', 'test'],
        form_schema: { fields: TALL_FORM_FIELDS },
      },
    }),
    'create tall form',
  )

  const entry = await expectJsonResponse<FormEntryResponse>(
    await page.request.post(`/api/process/forms/incident/${form.id}/entries/`, {
      headers: { Accept: 'application/json' },
      data: {
        entry_date: '2026-06-27',
        data: entryData(),
      },
    }),
    'create tall form entry',
  )

  const entriesResponse = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return (
      url.pathname === `/api/process/forms/incident/${form.id}/entries/` &&
      response.request().method() === 'GET'
    )
  })
  await page.goto(`/process-documents/forms/incident/${form.id}`)
  const entries = await entriesResponse
  expect(entries.ok(), `load entries: ${entries.status()} ${await entries.text()}`).toBeTruthy()
  await expect(autoId(page, 'FormEntries-title')).toHaveText(title)
  await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (1)')

  await autoId(page, `EntriesTable-edit-${entry.id}`).click()

  const dialog = autoId(page, 'FormEntries-edit-dialog')
  await expect(dialog).toBeVisible()

  const dialogBox = await dialog.boundingBox()
  expect(dialogBox, 'dialog should have a measurable layout box').not.toBeNull()
  expect(dialogBox!.y, 'dialog top should remain inside the viewport').toBeGreaterThanOrEqual(0)
  expect(
    dialogBox!.y + dialogBox!.height,
    'dialog bottom should remain inside the viewport',
  ).toBeLessThanOrEqual(640)

  const submitButton = dialog.locator('[data-automation-id="DynamicFormEntry-submit"]')
  await submitButton.scrollIntoViewIfNeeded()
  await expect(submitButton).toBeVisible()
  await expect(dialog.locator('[data-automation-id="FormEntries-edit-cancel"]')).toBeVisible()
})
