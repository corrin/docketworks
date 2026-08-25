import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { EntryOut, FormFieldSchema } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { EntryForm, type EntryFormSubmitBody, type StaffOption } from './EntryForm'

const ALL_JOBS = '*/api/purchasing/all-jobs/'
const SOURCE_ENTRIES = '*/api/process/forms/22222222-2222-2222-2222-222222222222/entries/'

const STAFF_OPTIONS: StaffOption[] = [
  { id: 'staff-1', name: 'Wendy Workshop' },
  { id: 'staff-2', name: 'Oscar Office' },
]

const FULL_SCHEMA: FormFieldSchema[] = [
  { key: 'notes', label: 'Notes', type: 'text', required: true },
  { key: 'details', label: 'Details', type: 'textarea' },
  { key: 'inspected_on', label: 'Inspected on', type: 'date' },
  { key: 'passed', label: 'Passed', type: 'boolean' },
  { key: 'count', label: 'Count', type: 'number' },
  { key: 'severity', label: 'Severity', type: 'select', options: ['low', 'high'] },
  { key: 'reported_by', label: 'Reported by', type: 'staff' },
  {
    key: 'asset',
    label: 'Asset',
    type: 'entry_ref',
    source_form: '22222222-2222-2222-2222-222222222222',
    display_key: 'name',
  },
]

function entryRow(overrides: Partial<EntryOut> = {}): EntryOut {
  return {
    id: '33333333-3333-3333-3333-333333333333',
    form: '22222222-2222-2222-2222-222222222222',
    entry_date: '2026-01-01',
    staff: null,
    staff_name: null,
    entered_by: null,
    entered_by_name: null,
    job: null,
    parent_entry: null,
    child_count: 0,
    data: { name: 'Grinder #1' },
    display_data: {},
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

const JOB_ROW = {
  id: 'job-1',
  job_number: 1001,
  name: 'Widget repair',
  status: 'in_progress',
  company_name: 'Acme Co',
}

function mockJobs(jobs: unknown[] = []): void {
  server.use(http.get(ALL_JOBS, () => HttpResponse.json({ success: true, jobs })))
  // The status vocabulary JobPicker reads on mount; not what any test here asserts.
  server.use(
    http.get('*/api/job/jobs/status-choices/', () =>
      HttpResponse.json({ statuses: { in_progress: 'In Progress' } }),
    ),
  )
}

function mockSourceEntries(): void {
  server.use(
    http.get(SOURCE_ENTRIES, () =>
      HttpResponse.json({
        results: [entryRow()],
        count: 1,
        page: 1,
        page_size: 100,
        total_pages: 1,
      }),
    ),
  )
}

function renderForm({
  schema = FULL_SCHEMA,
  onSubmit = vi.fn(),
  submitting = false,
  automationIdPrefix = 'EntryForm',
  disabled = false,
  initial,
}: {
  schema?: FormFieldSchema[]
  onSubmit?: (body: EntryFormSubmitBody) => void | Promise<void>
  submitting?: boolean
  automationIdPrefix?: string
  disabled?: boolean
  initial?: Parameters<typeof EntryForm>[0]['initial']
} = {}) {
  return {
    onSubmit,
    ...renderWithProviders(
      <EntryForm
        schema={schema}
        initial={initial}
        staffOptions={STAFF_OPTIONS}
        onSubmit={onSubmit}
        submitting={submitting}
        automationIdPrefix={automationIdPrefix}
        disabled={disabled}
      />,
    ),
  }
}

describe('EntryForm', () => {
  it('renders one control per schema field, matching its type', async () => {
    mockJobs()
    mockSourceEntries()
    renderForm()
    await waitFor(() =>
      expect(
        within(autoId('EntryForm-field-asset')).queryByRole('option', { name: 'Grinder #1' }),
      ).toBeInTheDocument(),
    )

    expect(autoId('EntryForm-field-notes').tagName).toBe('INPUT')
    expect(autoId('EntryForm-field-notes')).toHaveAttribute('type', 'text')
    expect(autoId('EntryForm-field-details').tagName).toBe('TEXTAREA')
    expect(autoId('EntryForm-field-inspected_on')).toHaveAttribute('type', 'date')
    expect(autoId('EntryForm-field-passed')).toHaveAttribute('type', 'checkbox')
    expect(autoId('EntryForm-field-count')).toHaveAttribute('type', 'number')
    expect(autoId('EntryForm-field-severity').tagName).toBe('SELECT')
    expect(screen.getByRole('option', { name: 'low' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'high' })).toBeInTheDocument()
    expect(autoId('EntryForm-field-reported_by').tagName).toBe('SELECT')
    expect(
      within(autoId('EntryForm-field-reported_by')).getByRole('option', { name: 'Wendy Workshop' }),
    ).toBeInTheDocument()
    expect(
      within(autoId('EntryForm-field-reported_by')).getByRole('option', { name: 'Oscar Office' }),
    ).toBeInTheDocument()
    expect(autoId('EntryForm-field-asset').tagName).toBe('SELECT')
    expect(
      within(autoId('EntryForm-field-asset')).getByRole('option', { name: 'Grinder #1' }),
    ).toBeInTheDocument()

    expect(autoId('EntryForm-entry-date')).toHaveAttribute('type', 'date')
    expect(autoId('EntryForm-staff').tagName).toBe('SELECT')
  })

  it('blocks submit and shows a validation line when a required field is blank', async () => {
    mockJobs()
    mockSourceEntries()
    const onSubmit = vi.fn()
    const { user } = renderForm({ onSubmit })
    await waitFor(() => expect(autoId('EntryForm-field-asset')).toBeInTheDocument())

    await user.click(autoId('EntryForm-submit'))

    expect(onSubmit).not.toHaveBeenCalled()
    expect(autoId('EntryForm-validation')).toHaveTextContent("'Notes' is required.")
  })

  it('submits entry_date/data/staff with numbers as numbers and booleans as booleans', async () => {
    mockJobs()
    mockSourceEntries()
    const onSubmit = vi.fn()
    const { user } = renderForm({
      onSubmit,
      schema: [
        { key: 'notes', label: 'Notes', type: 'text', required: true },
        { key: 'count', label: 'Count', type: 'number' },
        { key: 'passed', label: 'Passed', type: 'boolean' },
      ],
      initial: { entry_date: '2026-02-03', staff: 'staff-1' },
    })
    await waitFor(() => expect(autoId('EntryForm-entry-date')).toBeInTheDocument())

    await user.type(autoId('EntryForm-field-notes'), 'All clear')
    await user.clear(autoId('EntryForm-field-count'))
    await user.type(autoId('EntryForm-field-count'), '4')
    await user.click(autoId('EntryForm-field-passed'))
    await user.click(autoId('EntryForm-submit'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit).toHaveBeenCalledWith({
      entry_date: '2026-02-03',
      data: { notes: 'All clear', count: 4, passed: true },
      staff: 'staff-1',
      job: null,
      parent_entry: null,
    })
  })

  it('defaults the staff picker to the signed-in user via `initial.staff`', async () => {
    mockJobs()
    renderForm({ schema: [], initial: { staff: 'staff-2' } })
    await waitFor(() => expect(autoId('EntryForm-staff')).toBeInTheDocument())
    expect(autoId('EntryForm-staff')).toHaveValue('staff-2')
  })

  it('renders every control disabled in preview mode and never calls onSubmit', async () => {
    mockJobs()
    const onSubmit = vi.fn()
    renderForm({
      schema: [{ key: 'notes', label: 'Notes', type: 'text' }],
      disabled: true,
      onSubmit,
    })
    await waitFor(() => expect(autoId('EntryForm-field-notes')).toBeInTheDocument())

    expect(autoId('EntryForm-field-notes')).toBeDisabled()
    expect(autoId('EntryForm-entry-date')).toBeDisabled()
    expect(autoId('EntryForm-staff')).toBeDisabled()
    expect(autoId('EntryForm-submit')).toBeDisabled()
  })

  it('clears a linked job and submits job: null', async () => {
    mockJobs([JOB_ROW])
    const onSubmit = vi.fn()
    const { user } = renderForm({
      onSubmit,
      schema: [],
      initial: { job: 'job-1' },
    })
    await waitFor(() => expect(autoId('EntryForm-job-trigger')).toHaveTextContent('1001'))
    expect(autoId('EntryForm-job-clear')).toBeInTheDocument()

    await user.click(autoId('EntryForm-job-clear'))
    await waitFor(() => expect(queryAutoId('EntryForm-job-clear')).toBeNull())

    await user.click(autoId('EntryForm-submit'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ job: null }))
  })

  it('scopes every id under a distinct automationIdPrefix so two instances never collide', async () => {
    mockJobs()
    renderForm({
      schema: [{ key: 'notes', label: 'Notes', type: 'text' }],
      automationIdPrefix: 'EntryForm-edit',
    })
    await waitFor(() => expect(autoId('EntryForm-edit-field-notes')).toBeInTheDocument())
    expect(queryAutoId('EntryForm-field-notes')).toBeNull()
    expect(queryAutoId('EntryForm-submit')).toBeNull()
    expect(autoId('EntryForm-edit-submit')).toBeInTheDocument()
  })
})
