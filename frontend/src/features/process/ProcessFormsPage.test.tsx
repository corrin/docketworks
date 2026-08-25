import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import type { CategoriesOut, FormOut } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { mockUser } from '@/test/me'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { ProcessFormsPage } from './ProcessFormsPage'

const LIST = '*/api/process/forms/'
const DETAIL = '*/api/process/forms/:formId/'
const CATEGORIES = '*/api/process/categories/'

const CATEGORIES_RESPONSE: CategoriesOut = {
  forms: [
    { key: 'safety', label: 'Safety' },
    { key: 'training', label: 'Training' },
    { key: 'incident', label: 'Incident' },
    { key: 'meeting', label: 'Meeting' },
    { key: 'register', label: 'Register' },
  ],
  procedures: [],
}

function formRow(overrides: Partial<FormOut> = {}): FormOut {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    title: 'Toolbox Talk',
    document_number: 'SAF-001',
    category: 'safety',
    document_type: 'form',
    tags: ['weekly'],
    status: 'active',
    form_schema: { fields: [{ key: 'notes', label: 'Notes', type: 'textarea' }] },
    entry_count: 4,
    created_at: '2026-01-05T00:00:00Z',
    updated_at: '2026-01-06T00:00:00Z',
    ...overrides,
  }
}

async function renderPage() {
  const result = renderWithProviders(<ProcessFormsPage category="safety" />)
  await screen.findByText('Toolbox Talk')
  return result
}

describe('ProcessFormsPage', () => {
  beforeEach(() => {
    mockUser({ is_office_staff: true })
    server.use(
      http.get(LIST, () => HttpResponse.json([formRow()])),
      http.get(CATEGORIES, () => HttpResponse.json(CATEGORIES_RESPONSE)),
      // EntryForm's job picker (rendered disabled inside FormDialog's preview
      // and interactively inside the Fill dialog) queries these on mount.
      http.get('*/api/purchasing/all-jobs/', () => HttpResponse.json({ success: true, jobs: [] })),
      http.get('*/api/job/jobs/status-choices/', () => HttpResponse.json({ statuses: {} })),
      http.get('*/api/process/staff-options/', () => HttpResponse.json([])),
    )
  })

  it('lists forms with their doc number, tags and entry count', async () => {
    await renderPage()
    const row = autoId('ProcessFormsPage-row-11111111-1111-1111-1111-111111111111')
    expect(row).toHaveTextContent('Toolbox Talk')
    expect(row).toHaveTextContent('SAF-001')
    expect(row).toHaveTextContent('weekly')
    expect(row).toHaveTextContent('4')
  })

  it('hides archived forms by default and reveals them via the toggle', async () => {
    const requestedStatuses: (string | null)[] = []
    server.use(
      http.get(LIST, ({ request }) => {
        const status = new URL(request.url).searchParams.get('status')
        requestedStatuses.push(status)
        if (status === 'archived') {
          return HttpResponse.json([
            formRow({
              id: '22222222-2222-2222-2222-222222222222',
              title: 'Retired Talk',
              status: 'archived',
            }),
          ])
        }
        return HttpResponse.json([formRow()])
      }),
    )
    const { user } = await renderPage()

    // apps/process/api.py: status omitted excludes archived rows server-side.
    expect(requestedStatuses).toEqual([null])
    expect(queryAutoId('ProcessFormsPage-row-22222222-2222-2222-2222-222222222222')).toBeNull()

    await user.click(autoId('ProcessFormsPage-show-archived'))
    await screen.findByText('Retired Talk')
    expect(requestedStatuses).toEqual([null, 'archived'])
    expect(queryAutoId('ProcessFormsPage-row-11111111-1111-1111-1111-111111111111')).toBeNull()
  })

  it('clicking a row navigates away from the list', async () => {
    const { user } = await renderPage()
    await user.click(autoId('ProcessFormsPage-row-11111111-1111-1111-1111-111111111111'))
    // The shared render harness only registers /test and /kanban, so the
    // real destination (process-documents/forms/$category/$formId, wired up
    // in Task 12) has nowhere to render — the list unmounting is what proves
    // navigate() fired rather than the click being swallowed.
    await waitFor(() => expect(queryAutoId('ProcessFormsPage-root')).toBeNull())
  })

  it('New Form opens the create dialog', async () => {
    const { user } = await renderPage()
    await user.click(autoId('ProcessFormsPage-new-form'))
    await waitFor(() => expect(queryAutoId('FormDialog-cancel')).not.toBeNull())
    expect(autoId('FormDialog-schema')).toHaveValue(JSON.stringify({ fields: [] }, null, 2))
  })

  it('Fill opens the entry form and posts a created entry to the form', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post('*/api/process/forms/:formId/entries/', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(
          {
            id: 'e1111111-1111-1111-1111-111111111111',
            form: '11111111-1111-1111-1111-111111111111',
            entry_date: '2026-01-10',
            staff: null,
            staff_name: null,
            entered_by: '11111111-1111-1111-1111-111111111111',
            entered_by_name: 'Some One',
            job: null,
            parent_entry: null,
            child_count: 0,
            data: { notes: 'All clear' },
            display_data: {},
            is_active: true,
            created_at: '2026-01-10T00:00:00Z',
            updated_at: '2026-01-10T00:00:00Z',
          },
          { status: 201 },
        )
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('ProcessFormsPage-fill-11111111-1111-1111-1111-111111111111'))
    await waitFor(() => expect(queryAutoId('EntryForm-field-notes')).not.toBeNull())

    await user.type(autoId('EntryForm-field-notes'), 'All clear')
    await user.click(autoId('EntryForm-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ data: { notes: 'All clear' } })
  })

  it('Fill success invalidates the forms list so entry_count refreshes', async () => {
    let listCalls = 0
    server.use(
      http.get(LIST, () => {
        listCalls += 1
        // Second (post-invalidation) call reports the bumped count.
        return HttpResponse.json([formRow({ entry_count: listCalls === 1 ? 4 : 5 })])
      }),
      http.post('*/api/process/forms/:formId/entries/', () =>
        HttpResponse.json(
          {
            id: 'e1111111-1111-1111-1111-111111111111',
            form: '11111111-1111-1111-1111-111111111111',
            entry_date: '2026-01-10',
            staff: null,
            staff_name: null,
            entered_by: '11111111-1111-1111-1111-111111111111',
            entered_by_name: 'Some One',
            job: null,
            parent_entry: null,
            child_count: 0,
            data: { notes: 'All clear' },
            display_data: {},
            is_active: true,
            created_at: '2026-01-10T00:00:00Z',
            updated_at: '2026-01-10T00:00:00Z',
          },
          { status: 201 },
        ),
      ),
    )
    const { user } = await renderPage()
    const row = autoId('ProcessFormsPage-row-11111111-1111-1111-1111-111111111111')
    expect(row).toHaveTextContent('4')

    await user.click(autoId('ProcessFormsPage-fill-11111111-1111-1111-1111-111111111111'))
    await waitFor(() => expect(queryAutoId('EntryForm-field-notes')).not.toBeNull())
    await user.type(autoId('EntryForm-field-notes'), 'All clear')
    await user.click(autoId('EntryForm-submit'))

    await waitFor(() => expect(row).toHaveTextContent('5'))
  })

  it('Fill shows the no-schema message for a form with no fields', async () => {
    server.use(http.get(LIST, () => HttpResponse.json([formRow({ form_schema: { fields: [] } })])))
    const { user } = await renderPage()

    await user.click(autoId('ProcessFormsPage-fill-11111111-1111-1111-1111-111111111111'))
    await screen.findByText('This document has no form schema defined. Entries cannot be added.')
    expect(queryAutoId('EntryForm-submit')).toBeNull()
  })

  it('hides Edit from non-office staff; the API rejects the write regardless', async () => {
    mockUser({ is_office_staff: false })
    await renderPage()
    expect(queryAutoId('ProcessFormsPage-edit-11111111-1111-1111-1111-111111111111')).toBeNull()
  })

  it('an invalid schema blocks submit and shows the parse error', async () => {
    const { user } = await renderPage()
    await user.click(autoId('ProcessFormsPage-new-form'))
    await waitFor(() => expect(queryAutoId('FormDialog-cancel')).not.toBeNull())

    await user.type(autoId('FormDialog-title'), 'New Register')
    await user.selectOptions(autoId('FormDialog-category'), 'safety')
    await user.selectOptions(autoId('FormDialog-document-type'), 'form')
    await user.clear(autoId('FormDialog-schema'))
    await user.type(autoId('FormDialog-schema'), 'not valid json')
    await user.click(autoId('FormDialog-submit'))

    expect(autoId('FormDialog-validation')).toHaveTextContent('Schema must be valid JSON')
    expect(autoId('FormDialog-schema-error')).toBeInTheDocument()
  })

  it('creates a form with its parsed schema in the POST body', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post(LIST, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(formRow({ title: 'New Register' }), { status: 201 })
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('ProcessFormsPage-new-form'))
    await waitFor(() => expect(queryAutoId('FormDialog-cancel')).not.toBeNull())
    await user.type(autoId('FormDialog-title'), 'New Register')
    await user.selectOptions(autoId('FormDialog-category'), 'safety')
    await user.selectOptions(autoId('FormDialog-document-type'), 'form')
    await user.click(autoId('FormDialog-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      title: 'New Register',
      category: 'safety',
      document_type: 'form',
      form_schema: { fields: [] },
    })
  })

  it('round-trips an edited schema: pre-populated, then PATCHes only the edit', async () => {
    // The regression this dialog exists to fix: v1's edit form never loaded
    // form_schema into the textarea and never sent it back on save, so every
    // edit silently wiped the form's fields.
    const bodies: unknown[] = []
    server.use(
      http.patch(DETAIL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(formRow())
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('ProcessFormsPage-edit-11111111-1111-1111-1111-111111111111'))
    await screen.findByText('Edit Form')

    const original = formRow()
    expect(autoId('FormDialog-schema')).toHaveValue(JSON.stringify(original.form_schema, null, 2))

    // Braces defeat userEvent.type's key-sequence parser, so the edit is
    // applied as a single programmatic value change rather than keystrokes.
    const edited = { fields: [{ key: 'notes', label: 'Notes Updated', type: 'textarea' }] }
    fireEvent.change(autoId('FormDialog-schema'), {
      target: { value: JSON.stringify(edited, null, 2) },
    })
    await user.click(autoId('FormDialog-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    // Only form_schema changed — title/category/document_number/tags/status
    // must stay off the wire (exclude_unset dirty-only PATCH).
    expect(bodies[0]).toEqual({ form_schema: edited })
  })

  it('archiving a form via the dialog sends only the status flip', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch(DETAIL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(formRow({ status: 'archived' }))
      }),
    )
    const { user } = await renderPage()

    await user.click(autoId('ProcessFormsPage-edit-11111111-1111-1111-1111-111111111111'))
    await screen.findByText('Edit Form')
    expect(autoId('FormDialog-archived')).not.toBeChecked()

    await user.click(autoId('FormDialog-archived'))
    await user.click(autoId('FormDialog-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ status: 'archived' })
  })

  it('the archive control is absent when creating a new form', async () => {
    const { user } = await renderPage()
    await user.click(autoId('ProcessFormsPage-new-form'))
    await waitFor(() => expect(queryAutoId('FormDialog-cancel')).not.toBeNull())
    expect(queryAutoId('FormDialog-archived')).toBeNull()
  })
})
