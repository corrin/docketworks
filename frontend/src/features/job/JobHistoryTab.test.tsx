import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { PhoneCallRecordOut, TimelineEntryOut } from '@/api'
import { getFullJobOptions } from '@/api'
import { allAutoIds, autoId, queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { JobHistoryTab } from './JobHistoryTab'

// The linked-calls table is task 2's component with its own tests, its own
// link/unlink mutations and an <audio> per row; stubbing it keeps these
// assertions about what the History tab hands it.
vi.mock('@/features/crm', () => ({
  PhoneCallTable: (props: {
    rows: readonly PhoneCallRecordOut[] | undefined
    emptyLabel: string
    allowJobLinking: boolean
  }) => (
    <div
      data-automation-id="PhoneCallTable"
      data-rows={props.rows === undefined ? 'unloaded' : props.rows.map((row) => row.id).join(',')}
      data-empty-label={props.emptyLabel}
      data-allow-job-linking={String(props.allowJobLinking)}
    />
  ),
}))

const JOB_ID = '0b54b371-4d33-49e7-be29-31bd93bc78cf'

function mockUser(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get('*/api/accounts/me/', () =>
      HttpResponse.json({
        id: '11111111-1111-1111-1111-111111111111',
        office_email: 'someone@example.com',
        payroll_email: null,
        first_name: 'Some',
        last_name: 'One',
        preferred_name: null,
        fullName: 'Some One',
        is_office_staff: true,
        is_superuser: false,
        ...overrides,
      }),
    ),
  )
}

function entry(overrides: Partial<TimelineEntryOut> = {}): TimelineEntryOut {
  return {
    can_undo: null,
    change_id: null,
    cost_set_kind: null,
    costline_kind: null,
    created_at: null,
    delta_after: null,
    delta_before: null,
    delta_checksum: null,
    delta_meta: null,
    description: 'Job created',
    entry_type: 'event',
    event_type: 'manual_note',
    id: 'event-1',
    quantity: null,
    schema_version: null,
    staff: 'Alex Smith',
    timestamp: '2026-08-09T02:30:00Z',
    total_cost: null,
    total_rev: null,
    undo_description: null,
    unit_cost: null,
    unit_rev: null,
    updated_at: null,
    ...overrides,
  }
}

const undoableEntry = entry({
  id: 'event-2',
  description: 'Job name changed',
  event_type: 'manual_note',
  can_undo: true,
  change_id: 'change-9',
  undo_description: 'Revert name to Gate frame',
  delta_before: { name: 'Gate frame' },
  delta_after: { name: 'Gate frame mk2' },
})

/** Records every timeline request and answers with these entries. */
function serveTimeline(entries: TimelineEntryOut[]): { calls: number } {
  const seen = { calls: 0 }
  server.use(
    http.get(`*/api/job/jobs/${JOB_ID}/timeline/`, () => {
      seen.calls += 1
      return HttpResponse.json({ timeline: entries })
    }),
  )
  return seen
}

/** Records every linked-calls request and answers with one page. */
function servePhoneCalls(rows: PhoneCallRecordOut[] = [], count = rows.length): { urls: URL[] } {
  const seen: { urls: URL[] } = { urls: [] }
  server.use(
    http.get('*/api/crm/phone-calls/', ({ request }) => {
      seen.urls.push(new URL(request.url))
      return HttpResponse.json({ count, page: 1, page_size: 50, results: rows, total_pages: 1 })
    }),
  )
  return seen
}

function phoneCall(): PhoneCallRecordOut {
  return {
    account_code: 'ACC',
    call_date: '2026-08-09',
    call_datetime: '2026-08-09T02:30:00Z',
    call_time: '02:30:00',
    call_type: 'voice',
    charge: null,
    company: 'company-1',
    company_name: 'Alpha Engineering',
    description: null,
    destination: null,
    destination_endpoint: null,
    destination_endpoint_label: '',
    direction: 'inbound',
    duration_seconds: 67,
    external_number: '+6421555111',
    id: 'call-1',
    imported_at: '2026-08-09T02:31:00Z',
    job: JOB_ID,
    job_linked_at: '2026-08-09T02:40:00Z',
    job_linked_by: null,
    job_name: 'Gate frame',
    job_number: 1234,
    job_status: 'in_progress',
    origin: null,
    origin_endpoint: null,
    origin_endpoint_label: '',
    our_number: '+6435551000',
    person: null,
    person_name: 'Alex Smith',
    provider_call_id: 'prov-call-1',
    recording: null,
    status: 'answered',
    updated_at: '2026-08-09T02:31:00Z',
  }
}

describe('JobHistoryTab — who may write', () => {
  it('offers workshop staff the timeline alone: no calls, no Add Event, no Undo', async () => {
    mockUser({ is_office_staff: false })
    serveTimeline([undoableEntry])
    const calls = servePhoneCalls([phoneCall()])

    renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(queryAutoId(`JobHistoryTab-entry-event-event-2`)).not.toBeNull())
    // The three write surfaces are all office_auth on the backend; v1 showed
    // Add Event and Undo to everyone and let the request 403.
    expect(queryAutoId('JobHistoryTab-add-event-toggle')).toBeNull()
    expect(queryAutoId('JobHistoryTab-undo-toggle-event-2')).toBeNull()
    expect(queryAutoId('PhoneCallTable')).toBeNull()
    expect(calls.urls).toHaveLength(0)
  })

  it('asks for this job’s first fifty calls for office staff', async () => {
    mockUser()
    serveTimeline([])
    const calls = servePhoneCalls([phoneCall()], 3)

    renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(calls.urls).toHaveLength(1))
    const asked = calls.urls[0]
    if (asked === undefined) throw new Error('the linked calls were never requested')
    expect(Object.fromEntries(asked.searchParams.entries())).toEqual({
      job: JOB_ID,
      page: '1',
      page_size: '50',
    })

    const table = await screen.findByText('Showing 1 of 3')
    expect(table).toBeInTheDocument()
    expect(autoId('PhoneCallTable').dataset.rows).toBe('call-1')
    expect(autoId('PhoneCallTable').dataset.emptyLabel).toBe('No linked phone calls')
    // v1 allowed Change/Unlink from the History tab, and the backend still does.
    expect(autoId('PhoneCallTable').dataset.allowJobLinking).toBe('true')
  })
})

describe('JobHistoryTab — the timeline', () => {
  it('renders an event, a cost-line creation and that line’s later update', async () => {
    mockUser({ is_office_staff: false })
    serveTimeline([
      entry(),
      entry({
        id: 'line-1',
        entry_type: 'costline_created',
        event_type: null,
        cost_set_kind: 'estimate',
        costline_kind: 'time',
        description: 'Cutting (2.00 hours)',
      }),
      entry({
        id: 'line-1',
        entry_type: 'costline_updated',
        event_type: null,
        cost_set_kind: 'estimate',
        costline_kind: 'time',
        description: 'Cutting (3.00 hours)',
      }),
    ])
    servePhoneCalls()

    renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(queryAutoId('JobHistoryTab-timeline')).not.toBeNull())
    // One cost line's creation and update share an id; v1 keyed the list on
    // the id alone and React dropped the second row.
    expect(autoId('JobHistoryTab-entry-costline_created-line-1')).toBeInTheDocument()
    expect(autoId('JobHistoryTab-entry-costline_updated-line-1')).toBeInTheDocument()

    const event = autoId('JobHistoryTab-entry-event-event-1')
    expect(event).toHaveTextContent('Job created')
    expect(event).toHaveTextContent('Manual Note')
    expect(event).toHaveTextContent('Alex Smith')

    const created = autoId('JobHistoryTab-entry-costline_created-line-1')
    expect(created).toHaveTextContent('Costline Created')
    expect(created).toHaveTextContent('Estimate - time')

    // The v1 defect: an updated cost line rendered as a "General" job event.
    expect(autoId('JobHistoryTab-entry-costline_updated-line-1')).toHaveTextContent(
      'Costline Updated',
    )
    expect(queryAutoId('JobHistoryTab-empty')).toBeNull()
  })

  it('says so when the job has no history yet', async () => {
    mockUser({ is_office_staff: false })
    serveTimeline([])
    servePhoneCalls()

    renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    expect(await screen.findByText('No events recorded yet')).toBeInTheDocument()
    expect(autoId('JobHistoryTab-empty')).toBeInTheDocument()
  })

  it('offers a Retry rather than an empty timeline when the fetch fails', async () => {
    mockUser({ is_office_staff: false })
    let attempts = 0
    server.use(
      http.get(`*/api/job/jobs/${JOB_ID}/timeline/`, () => {
        attempts += 1
        if (attempts === 1) return HttpResponse.json({ detail: 'boom' }, { status: 500 })
        return HttpResponse.json({ timeline: [entry()] })
      }),
    )
    servePhoneCalls()

    const { user } = renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    expect(await screen.findByText('Failed to load the job timeline.')).toBeInTheDocument()
    // An unreadable timeline must never masquerade as a job with no history.
    expect(queryAutoId('JobHistoryTab-empty')).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(queryAutoId('JobHistoryTab-entry-event-event-1')).not.toBeNull())
  })

  it('shows no undo control for an entry the backend cannot undo', async () => {
    mockUser()
    serveTimeline([entry({ can_undo: false, change_id: 'change-9' }), entry({ id: 'event-3' })])
    servePhoneCalls()

    renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(queryAutoId('JobHistoryTab-entry-event-event-1')).not.toBeNull())
    expect(queryAutoId('JobHistoryTab-undo-toggle-event-1')).toBeNull()
    // can_undo null (a cost line, or an event with no delta) is equally not undoable.
    expect(queryAutoId('JobHistoryTab-undo-toggle-event-3')).toBeNull()
    expect(allAutoIds('JobHistoryTab-undo-toggle-event-1')).toHaveLength(0)
  })
})

describe('JobHistoryTab — adding an event', () => {
  it('posts the description, reloads the timeline and closes the form', async () => {
    mockUser()
    const timeline = serveTimeline([entry()])
    servePhoneCalls()
    const posted: unknown[] = []
    server.use(
      http.post(`*/api/job/jobs/${JOB_ID}/events/create/`, async ({ request }) => {
        posted.push(await request.json())
        return HttpResponse.json(
          {
            success: true,
            event: {
              id: 'event-9',
              description: 'Customer called back',
              timestamp: '2026-08-09T03:00:00Z',
              staff: 'Some One',
              event_type: 'manual_note',
              can_undo: false,
              change_id: null,
            },
          },
          { status: 201 },
        )
      }),
    )

    const { user } = renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(queryAutoId('JobHistoryTab-add-event-toggle')).not.toBeNull())
    await user.click(autoId('JobHistoryTab-add-event-toggle'))

    const submit = autoId('JobHistoryTab-add-event-submit')
    // Nothing to record yet: an empty event would be a blank timeline row.
    expect(submit).toBeDisabled()

    await user.type(autoId('JobHistoryTab-event-description'), 'Customer called back')
    expect(submit).toBeEnabled()
    await user.click(submit)

    expect(await screen.findByText('Event added')).toBeInTheDocument()
    expect(posted).toEqual([{ description: 'Customer called back' }])
    await waitFor(() => expect(timeline.calls).toBe(2))
    // The form closes and empties, so the next event does not start half-typed.
    await waitFor(() => expect(queryAutoId('JobHistoryTab-event-description')).toBeNull())
  })

  it('surfaces the backend’s own refusal', async () => {
    mockUser()
    serveTimeline([entry()])
    servePhoneCalls()
    server.use(
      http.post(`*/api/job/jobs/${JOB_ID}/events/create/`, () =>
        HttpResponse.json({ detail: 'Too many events; slow down.' }, { status: 429 }),
      ),
    )

    const { user } = renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(queryAutoId('JobHistoryTab-add-event-toggle')).not.toBeNull())
    await user.click(autoId('JobHistoryTab-add-event-toggle'))
    await user.type(autoId('JobHistoryTab-event-description'), 'Customer called back')
    await user.click(autoId('JobHistoryTab-add-event-submit'))

    expect(await screen.findByText('Too many events; slow down.')).toBeInTheDocument()
    // The description survives a refusal; retyping it would be the punishment
    // for the server's rate limit.
    expect(autoId('JobHistoryTab-event-description')).toHaveValue('Customer called back')
  })
})

describe('JobHistoryTab — undoing a change', () => {
  it('reveals the delta, posts the change id, and re-reads job and timeline', async () => {
    mockUser()
    const timeline = serveTimeline([undoableEntry])
    servePhoneCalls()
    const posted: unknown[] = []
    server.use(
      http.post(`*/api/job/jobs/${JOB_ID}/undo-change/`, async ({ request }) => {
        posted.push(await request.json())
        return HttpResponse.json({ success: true, data: { job: { id: JOB_ID } } })
      }),
    )

    const { user, queryClient } = renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)
    const invalidated = vi.spyOn(queryClient, 'invalidateQueries')

    await waitFor(() => expect(queryAutoId('JobHistoryTab-undo-toggle-event-2')).not.toBeNull())
    await user.click(autoId('JobHistoryTab-undo-toggle-event-2'))

    expect(await screen.findByText('Revert name to Gate frame')).toBeInTheDocument()
    expect(autoId('JobHistoryTab-undo-before-event-2')).toHaveTextContent('name: Gate frame')
    expect(autoId('JobHistoryTab-undo-after-event-2')).toHaveTextContent('name: Gate frame mk2')

    await user.click(autoId('JobHistoryTab-undo-confirm-event-2'))

    expect(await screen.findByText('Change undone successfully')).toBeInTheDocument()
    expect(posted).toEqual([{ change_id: 'change-9' }])
    await waitFor(() => expect(timeline.calls).toBe(2))
    // The header's inline edits read the job-detail cache, so it is re-read
    // rather than reloaded — v1 called window.location.reload() here.
    const jobKey = getFullJobOptions({ path: { job_id: JOB_ID } }).queryKey
    expect(invalidated).toHaveBeenCalledWith({ queryKey: jobKey })
    // The panel closes: its delta describes a change that has been reverted.
    await waitFor(() => expect(queryAutoId('JobHistoryTab-undo-before-event-2')).toBeNull())
  })

  it('re-reads the timeline when the undo is refused, because it is stale', async () => {
    mockUser()
    const timeline = serveTimeline([undoableEntry])
    servePhoneCalls()
    server.use(
      http.post(`*/api/job/jobs/${JOB_ID}/undo-change/`, () =>
        HttpResponse.json({ detail: 'This change has already been undone.' }, { status: 409 }),
      ),
    )

    const { user } = renderWithProviders(<JobHistoryTab jobId={JOB_ID} />)

    await waitFor(() => expect(queryAutoId('JobHistoryTab-undo-toggle-event-2')).not.toBeNull())
    await user.click(autoId('JobHistoryTab-undo-toggle-event-2'))
    await user.click(autoId('JobHistoryTab-undo-confirm-event-2'))

    expect(await screen.findByText('This change has already been undone.')).toBeInTheDocument()
    await waitFor(() => expect(timeline.calls).toBe(2))
  })
})
