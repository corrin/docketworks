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

test('tall form entries page scrolls to saved entries', async ({ authenticatedPage: page }) => {
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

  await expectJsonResponse(
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

  const mainScrollState = await page.locator('main').evaluate((main) => {
    return {
      clientHeight: main.clientHeight,
      scrollHeight: main.scrollHeight,
      overflowY: window.getComputedStyle(main).overflowY,
    }
  })
  expect(mainScrollState.scrollHeight).toBeGreaterThan(mainScrollState.clientHeight)
  expect(mainScrollState.overflowY).toBe('auto')

  await page.locator('main').hover({ position: { x: 200, y: 400 } })
  await page.mouse.wheel(0, 1400)
  await expect(autoId(page, 'FormEntries-entries-count')).toBeInViewport()
  await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (1)')
})
