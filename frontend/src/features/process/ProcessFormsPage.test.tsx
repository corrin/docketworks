import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import type { CategoriesOut, FormOut } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { mockUser } from '@/test/me'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { ProcessFormsPage } from './ProcessFormsPage'

const LIST = '*/api/process/forms/'
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

  it('renders the Fill button disabled — Task 12 wires it up', async () => {
    await renderPage()
    expect(autoId('ProcessFormsPage-fill-11111111-1111-1111-1111-111111111111')).toBeDisabled()
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
})
