/**
 * Regression: the form-entries page must scroll to the entries table on a
 * small viewport (v1 KAN-160 — "Partial fix on this bug. Still can't scroll").
 * Seeds over the API; e2e_cleanup sweeps the [TEST] form and its entries.
 */

import { z } from 'zod'

import { expect, test } from '../fixtures/auth'
import { autoId } from '../helpers'

const TALL_FORM_FIELDS = [
  { key: 'incident_date', label: 'Incident date', type: 'date', required: true },
  { key: 'reported_by', label: 'Reported by', type: 'text' },
  { key: 'location', label: 'Location', type: 'text' },
  { key: 'description', label: 'Description', type: 'textarea' },
  { key: 'immediate_action', label: 'Immediate action', type: 'textarea' },
  { key: 'root_cause', label: 'Root cause', type: 'textarea' },
  { key: 'corrective_action', label: 'Corrective action', type: 'textarea' },
  { key: 'witnesses', label: 'Witnesses', type: 'textarea' },
  { key: 'equipment_involved', label: 'Equipment involved', type: 'textarea' },
  { key: 'notes', label: 'Notes', type: 'textarea' },
]

function entryData(): Record<string, string> {
  return Object.fromEntries(
    TALL_FORM_FIELDS.map((field) => [
      field.key,
      field.type === 'date' ? '2026-06-27' : `${field.label} test value`,
    ]),
  )
}

const createdForm = z.object({ id: z.string() })

test('tall form entries page scrolls to saved entries', async ({ authenticatedPage: page }) => {
  await page.setViewportSize({ width: 390, height: 640 })

  const title = `[TEST] Tall Incident Form ${Date.now()}`
  let formId = ''

  await test.step('seed a tall form and one entry over the API', async () => {
    const formResponse = await page.request.post('/api/process/forms/', {
      data: {
        document_type: 'form',
        category: 'incident',
        title,
        document_number: `KAN-160-${Date.now()}`,
        tags: ['incident', 'test'],
        form_schema: { fields: TALL_FORM_FIELDS },
      },
    })
    if (!formResponse.ok()) {
      throw new Error(`Form seed failed: ${formResponse.status()} ${await formResponse.text()}`)
    }
    formId = createdForm.parse(await formResponse.json()).id

    const entryResponse = await page.request.post(`/api/process/forms/${formId}/entries/`, {
      data: { entry_date: '2026-06-27', data: entryData() },
    })
    if (!entryResponse.ok()) {
      throw new Error(`Entry seed failed: ${entryResponse.status()} ${await entryResponse.text()}`)
    }
  })

  await test.step('the page overflows and the entries heading scrolls into view', async () => {
    const entriesLoaded = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/process/forms/${formId}/entries/`) &&
        response.request().method() === 'GET' &&
        response.ok(),
    )
    await page.goto(`/process-documents/forms/incident/${formId}`)
    await entriesLoaded

    await expect(autoId(page, 'FormEntries-title')).toHaveText(title)

    // v1's spec scrolled a Vue-router `<main>` with its own overflow-y:auto.
    // v2's _authed shell (frontend/src/routes/_authed.tsx) only locks body
    // scroll on desktop for routes that opt into `lockBodyScrollOnDesktop`
    // (kanban does; process-documents does not — see
    // frontend/src/routes/_authed/process-documents/**), and neither
    // ProcessFormsPage nor FormEntriesPage renders a <main> or any other
    // overflow-y container, so the document itself is the scrolling element.
    const overflows = await page.evaluate(() => {
      const scroller = document.scrollingElement
      return scroller !== null && scroller.scrollHeight > scroller.clientHeight
    })
    expect(overflows).toBe(true)

    await page.mouse.move(200, 300)
    await page.mouse.wheel(0, 1400)
    await expect(autoId(page, 'FormEntries-entries-count')).toBeInViewport()
    await expect(autoId(page, 'FormEntries-entries-count')).toHaveText('Entries (1)')
  })
})
