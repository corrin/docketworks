import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EntryOut, FormOut, PaginatedEntryList, StaffOptionOut } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { mockUser } from '@/test/me'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { FormEntriesPage } from './FormEntriesPage'

const FORM_ID = '22222222-2222-2222-2222-222222222222'
const FORM_URL = `*/api/process/forms/${FORM_ID}/`
const ENTRIES_URL = `*/api/process/forms/${FORM_ID}/entries/`
const HISTORY_URL = '*/api/process/entries/:entryId/history/'
const ENTRY_DETAIL_URL = '*/api/process/entries/:entryId/'
const CROSS_FORM_ENTRIES_URL = '*/api/process/entries/'
const FORMS_LIST_URL = '*/api/process/forms/'
const STAFF_OPTIONS_URL = '*/api/process/staff-options/'
const ALL_JOBS_URL = '*/api/purchasing/all-jobs/'
const STATUS_CHOICES_URL = '*/api/job/jobs/status-choices/'

const STAFF_OPTIONS: StaffOptionOut[] = [
  { id: '11111111-1111-1111-1111-111111111111', name: 'Some One' },
  { id: 'staff-2', name: 'Oscar Office' },
]

function form(overrides: Partial<FormOut> = {}): FormOut {
  return {
    id: FORM_ID,
    title: 'Toolbox Talk',
    document_number: 'SAF-001',
    category: 'safety',
    document_type: 'form',
    tags: ['weekly'],
    status: 'active',
    form_schema: { fields: [{ key: 'notes', label: 'Notes', type: 'text', required: true }] },
    entry_count: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function entryRow(overrides: Partial<EntryOut> = {}): EntryOut {
  return {
    id: '33333333-3333-3333-3333-333333333333',
    form: FORM_ID,
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
    ...overrides,
  }
}

function entriesPage(
  rows: EntryOut[],
  overrides: Partial<PaginatedEntryList> = {},
): PaginatedEntryList {
  return { results: rows, count: rows.length, page: 1, page_size: 20, total_pages: 1, ...overrides }
}

async function renderPage(formOverrides: Partial<FormOut> = {}, rows: EntryOut[] = [entryRow()]) {
  server.use(
    http.get(FORM_URL, () => HttpResponse.json(form(formOverrides))),
    http.get(ENTRIES_URL, () => HttpResponse.json(entriesPage(rows))),
  )
  const result = renderWithProviders(<FormEntriesPage category="safety" formId={FORM_ID} />)
  await screen.findByText('Toolbox Talk')
  return result
}

describe('FormEntriesPage', () => {
  beforeEach(() => {
    mockUser({ is_office_staff: true })
    server.use(
      http.get(STAFF_OPTIONS_URL, () => HttpResponse.json(STAFF_OPTIONS)),
      http.get(ALL_JOBS_URL, () => HttpResponse.json({ success: true, jobs: [] })),
      http.get(STATUS_CHOICES_URL, () => HttpResponse.json({ statuses: {} })),
      http.get(FORMS_LIST_URL, () => HttpResponse.json([form()])),
    )
  })

  it('renders the title, entries count and table from the mocked queries', async () => {
    await renderPage({}, [entryRow()])

    expect(autoId('FormEntries-title')).toHaveTextContent('Toolbox Talk')
    expect(autoId('FormEntries-entries-count')).toHaveTextContent('Entries (1)')
    expect(autoId('EntriesTable-row-33333333-3333-3333-3333-333333333333')).toHaveTextContent(
      'All clear',
    )
  })

  it('shows the no-schema message and hides the add-entry card for a form with no fields', async () => {
    await renderPage({ form_schema: { fields: [] } }, [])

    expect(
      screen.getByText('This document has no form schema defined. Entries cannot be added.'),
    ).toBeInTheDocument()
    expect(queryAutoId('FormEntries-add-entry')).toBeNull()
    expect(autoId('FormEntries-entries-count')).toHaveTextContent('Entries (0)')
  })

  it('creates an entry from the add-entry card, defaulting staff to the signed-in user', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post(ENTRIES_URL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(entryRow(), { status: 201 })
      }),
    )
    const { user } = await renderPage({}, [])
    await waitFor(() =>
      expect(autoId('EntryForm-staff')).toHaveValue('11111111-1111-1111-1111-111111111111'),
    )

    await user.type(autoId('EntryForm-field-notes'), 'Checked')
    await user.click(autoId('EntryForm-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({
      data: { notes: 'Checked' },
      staff: '11111111-1111-1111-1111-111111111111',
    })
  })

  it('edits an entry, PATCHing only the changed fields', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch(ENTRY_DETAIL_URL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(entryRow({ data: { notes: 'Updated' } }))
      }),
    )
    const entry = entryRow()
    const { user } = await renderPage({}, [entry])

    await user.click(autoId(`EntriesTable-edit-${entry.id}`))
    await screen.findByText('Edit entry')
    expect(autoId('EntryForm-edit-field-notes')).toHaveValue('All clear')

    await user.clear(autoId('EntryForm-edit-field-notes'))
    await user.type(autoId('EntryForm-edit-field-notes'), 'Updated')
    await user.click(autoId('EntryForm-edit-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ data: { notes: 'Updated' } })
  })

  it('archives an entry after confirmation', async () => {
    let deleted = false
    server.use(
      http.delete(ENTRY_DETAIL_URL, () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const entry = entryRow()
    const { user } = await renderPage({}, [entry])

    await user.click(autoId(`EntriesTable-archive-${entry.id}`))

    await waitFor(() => expect(deleted).toBe(true))
  })

  it('does not archive when the confirmation is declined', async () => {
    let deleted = false
    server.use(
      http.delete(ENTRY_DETAIL_URL, () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const entry = entryRow()
    const { user } = await renderPage({}, [entry])

    await user.click(autoId(`EntriesTable-archive-${entry.id}`))

    expect(deleted).toBe(false)
  })

  it('shows an entry’s history', async () => {
    server.use(
      http.get(HISTORY_URL, () =>
        HttpResponse.json([
          {
            id: 'ev-1',
            timestamp: '2026-01-10T00:00:00Z',
            event_type: 'entry_created',
            staff_name: 'Some One',
            description: 'Entry created',
            changes: [],
          },
        ]),
      ),
    )
    const entry = entryRow()
    const { user } = await renderPage({}, [entry])

    await user.click(autoId(`EntriesTable-history-${entry.id}`))

    await screen.findByText('Entry created')
  })

  it('groups linked entries by their child form and can add one', async () => {
    const childForm = form({
      id: '44444444-4444-4444-4444-444444444444',
      title: 'Corrective Action',
    })
    const bodies: unknown[] = []
    server.use(
      http.get(FORMS_LIST_URL, () => HttpResponse.json([form(), childForm])),
      http.get(CROSS_FORM_ENTRIES_URL, () => HttpResponse.json(entriesPage([]))),
      http.post(`*/api/process/forms/${childForm.id}/entries/`, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(entryRow({ form: childForm.id }), { status: 201 })
      }),
    )
    const entry = entryRow()
    const { user } = await renderPage({}, [entry])

    await user.click(autoId(`EntriesTable-links-${entry.id}`))
    await screen.findByText('Linked entries')
    expect(autoId('LinkedEntriesDialog-empty')).toBeInTheDocument()

    await user.selectOptions(autoId('LinkedEntriesDialog-add-form'), childForm.id)
    await waitFor(() =>
      expect(queryAutoId(`EntryForm-link-${childForm.id}-field-notes`)).not.toBeNull(),
    )
    await user.type(autoId(`EntryForm-link-${childForm.id}-field-notes`), 'Follow up')
    await user.click(autoId(`EntryForm-link-${childForm.id}-submit`))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toMatchObject({ parent_entry: entry.id, data: { notes: 'Follow up' } })
  })
})
