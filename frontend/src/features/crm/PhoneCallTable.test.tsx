import { useQuery } from '@tanstack/react-query'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import {
  crmPhoneCallsListOptions,
  type CompanyJobHeader,
  type PhoneCallRecordOut,
  type PhoneCallRecordingOut,
} from '@/api'
import { allAutoIds, autoId, queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { PhoneCallTable } from './PhoneCallTable'

function recording(overrides: Partial<PhoneCallRecordingOut> = {}): PhoneCallRecordingOut {
  return {
    account_code: 'ACC',
    archive_error: null,
    archived_at: null,
    byte_size: 2048,
    content_type: 'audio/wav',
    created_at: '2026-08-09T02:30:00Z',
    duration_ms: 65_000,
    download_url: '/api/crm/phone-call-recordings/rec-1/download/',
    filename: 'call.wav',
    id: 'rec-1',
    local_deleted_at: null,
    provider_delete_error: null,
    provider_deleted_at: null,
    provider_recording_id: 'prov-1',
    sha256: null,
    updated_at: '2026-08-09T02:30:00Z',
    ...overrides,
  }
}

/** 9 Aug 2026, 2:30 pm in whatever zone the runner sits in, so the rendered
    timestamp below is the same string everywhere. */
const CALL_AT = new Date(2026, 7, 9, 14, 30).toISOString()

function call(overrides: Partial<PhoneCallRecordOut> = {}): PhoneCallRecordOut {
  return {
    account_code: 'ACC',
    attempt_count: 1,
    call_date: '2026-08-09',
    call_datetime: CALL_AT,
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
    job: null,
    job_linked_at: null,
    job_linked_by: null,
    job_name: '',
    job_number: null,
    job_status: '',
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
    ...overrides,
  }
}

const linkedCall = call({
  job: 'job-1',
  job_name: 'Fabricate frame',
  job_number: 101,
  job_status: 'in_progress',
  job_linked_at: '2026-08-09T03:00:00Z',
})

const unmatchedCall = call({ id: 'call-2', company: null, company_name: '', person_name: '' })

function companyJob(overrides: Partial<CompanyJobHeader> = {}): CompanyJobHeader {
  return {
    company: { id: 'company-1', name: 'Alpha Engineering' },
    fully_invoiced: false,
    has_quote_in_xero: false,
    is_fixed_price: false,
    job_id: 'job-1',
    job_number: 101,
    max_people: 1,
    min_people: 1,
    name: 'Fabricate frame',
    paid: false,
    pricing_methodology: 'time_materials',
    quote_acceptance_date: null,
    rejected_flag: false,
    speed_quality_tradeoff: 'balanced',
    status: 'in_progress',
    ...overrides,
  }
}

/** The status vocabulary JobPicker reads on mount; not what any test here asserts. */
function serveStatusChoices(): void {
  server.use(
    http.get('*/api/job/jobs/status-choices/', () =>
      HttpResponse.json({ statuses: { in_progress: 'In Progress' } }),
    ),
  )
}

function renderTable(props: Partial<Parameters<typeof PhoneCallTable>[0]> = {}) {
  return renderWithProviders(
    <PhoneCallTable
      isPending={false}
      isError={false}
      onRetry={() => undefined}
      rows={[call()]}
      emptyLabel="No calls found"
      {...props}
    />,
  )
}

/** The page's shape in miniature: a live list query feeding the table, so an
    invalidation after a mutation is observable as a second GET. */
function TableOverLiveList({
  onAssignNumber,
}: {
  onAssignNumber?: (call: PhoneCallRecordOut) => void
}) {
  const calls = useQuery(crmPhoneCallsListOptions())
  return (
    <PhoneCallTable
      isPending={calls.isPending}
      isError={calls.isError}
      onRetry={() => void calls.refetch()}
      rows={calls.data?.results}
      emptyLabel="No calls found"
      onAssignNumber={onAssignNumber}
    />
  )
}

function serveList(rows: PhoneCallRecordOut[]): { gets: number } {
  const counter = { gets: 0 }
  server.use(
    http.get('*/api/crm/phone-calls/', () => {
      counter.gets += 1
      return HttpResponse.json({
        count: rows.length,
        page: 1,
        page_size: 50,
        results: rows,
        total_pages: 1,
      })
    }),
  )
  return counter
}

describe('PhoneCallTable — the plain columns', () => {
  it('renders the call time, duration and direction', async () => {
    renderTable({
      rows: [
        call(),
        call({ id: 'call-3', duration_seconds: 45, direction: 'outbound' }),
        call({ id: 'call-4', duration_seconds: 0, direction: 'unknown' }),
      ],
    })

    await waitFor(() => expect(queryAutoId('PhoneCallTable-row-call-1')).not.toBeNull())
    expect(screen.getAllByText('09/08/2026, 2:30 pm')).toHaveLength(3)
    expect(screen.getByText('1m 07s')).toBeVisible()
    expect(screen.getByText('45s')).toBeVisible()
    expect(screen.getByText('0s')).toBeVisible()
    expect(screen.getByText('Inbound')).toBeVisible()
    expect(screen.getByText('Outbound')).toBeVisible()
    // The provider's own "unknown" reads as a label, never as the raw wire
    // value; a direction the wire does not declare throws instead
    // (phoneCallFilters.test.ts).
    expect(screen.getByText('Unknown')).toBeVisible()
  })

  it('says the queue is empty rather than drawing nothing', async () => {
    renderTable({ rows: [], emptyLabel: 'No calls found' })

    expect(await screen.findByText('No calls found')).toBeVisible()
  })
})

describe('PhoneCallTable — the job cell', () => {
  it('shows the linked job with Change and Unlink', async () => {
    renderTable({ rows: [linkedCall] })

    expect(await screen.findByText('Job #101')).toBeVisible()
    expect(autoId('PhoneCallTable-linked-job-call-1')).toHaveTextContent('Job #101')
    expect(screen.getByText('Fabricate frame')).toBeVisible()
    expect(queryAutoId('PhoneCallTable-change-job-call-1')).not.toBeNull()
    expect(queryAutoId('PhoneCallTable-unlink-job-call-1')).not.toBeNull()
    expect(queryAutoId('PhoneCallTable-link-job-call-1')).toBeNull()
  })

  it('offers Link job on a call that has a company but no job', async () => {
    renderTable()

    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-job-call-1')).not.toBeNull())
    expect(queryAutoId('PhoneCallTable-linked-job-call-1')).toBeNull()
    expect(screen.queryByText('Assign company first')).toBeNull()
  })

  it('asks for a company first on a call that has none', async () => {
    renderTable({ rows: [unmatchedCall] })

    expect(await screen.findByText('Assign company first')).toBeVisible()
    expect(queryAutoId('PhoneCallTable-link-job-call-2')).toBeNull()
  })

  it('keeps the per-row id distinct so a spec cannot read the wrong row', async () => {
    renderTable({
      rows: [
        linkedCall,
        call({ id: 'call-3', job: 'job-2', job_name: 'Weld rail', job_number: 202 }),
      ],
    })

    await screen.findByText('Job #101')
    expect(allAutoIds('PhoneCallTable-linked-job-call-1')).toHaveLength(1)
    expect(autoId('PhoneCallTable-linked-job-call-3')).toHaveTextContent('Job #202')
  })
})

describe('PhoneCallTable — the number cell', () => {
  it('offers Assign number on an unmatched call when the caller handles it', async () => {
    renderTable({ rows: [unmatchedCall], onAssignNumber: vi.fn() })

    await waitFor(() => expect(queryAutoId('PhoneCallTable-assign-number-call-2')).not.toBeNull())
  })

  it('withholds Assign number where the caller has nowhere to host the panel', async () => {
    renderTable({ rows: [unmatchedCall] })

    await waitFor(() => expect(queryAutoId('PhoneCallTable-row-call-2')).not.toBeNull())
    expect(queryAutoId('PhoneCallTable-assign-number-call-2')).toBeNull()
  })

  it('does not offer Assign number for a call already matched to a company', async () => {
    renderTable({ onAssignNumber: vi.fn() })

    await waitFor(() => expect(queryAutoId('PhoneCallTable-row-call-1')).not.toBeNull())
    expect(queryAutoId('PhoneCallTable-assign-number-call-1')).toBeNull()
  })

  it('hands the call back when Assign number is clicked', async () => {
    const onAssignNumber = vi.fn()
    const { user } = renderTable({ rows: [unmatchedCall], onAssignNumber })

    await waitFor(() => expect(queryAutoId('PhoneCallTable-assign-number-call-2')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-assign-number-call-2'))
    expect(onAssignNumber).toHaveBeenCalledWith(unmatchedCall)
  })
})

describe('PhoneCallTable — the recording cell', () => {
  it('renders an audio element that fetches nothing until it is played', async () => {
    renderTable({ rows: [call({ recording: recording() })] })

    await waitFor(() => expect(queryAutoId('PhoneCallTable-recording-call-1')).not.toBeNull())
    const audio = autoId('PhoneCallTable-recording-call-1')
    expect(audio.tagName).toBe('AUDIO')
    expect(audio).toHaveAttribute('preload', 'none')
    expect(audio).toHaveAttribute('src', '/api/crm/phone-call-recordings/rec-1/download/')
  })

  it('says so when there is no recording, or none that can be downloaded', async () => {
    renderTable({
      rows: [call(), call({ id: 'call-3', recording: recording({ download_url: null }) })],
    })

    await waitFor(() => expect(screen.getAllByText('No recording')).toHaveLength(2))
    expect(queryAutoId('PhoneCallTable-recording-call-1')).toBeNull()
    expect(queryAutoId('PhoneCallTable-recording-call-3')).toBeNull()
  })
})

describe('PhoneCallTable — unlinking', () => {
  it('deletes the link and refetches the list', async () => {
    const counter = serveList([linkedCall])
    const deletes: string[] = []
    server.use(
      http.delete('*/api/crm/phone-calls/:callId/job-link/', ({ params }) => {
        deletes.push(String(params.callId))
        return HttpResponse.json(call())
      }),
    )
    const { user } = renderWithProviders(<TableOverLiveList />)

    await screen.findByText('Job #101')
    expect(counter.gets).toBe(1)

    await user.click(autoId('PhoneCallTable-unlink-job-call-1'))
    await waitFor(() => expect(deletes).toEqual(['call-1']))
    await waitFor(() => expect(counter.gets).toBe(2))
  })

  it('surfaces the backend refusal verbatim', async () => {
    serveList([linkedCall])
    server.use(
      http.delete('*/api/crm/phone-calls/:callId/job-link/', () =>
        HttpResponse.json(
          { status: 'error', message: 'That call is already invoiced.' },
          { status: 400 },
        ),
      ),
    )
    const { user } = renderWithProviders(<TableOverLiveList />)

    await screen.findByText('Job #101')
    await user.click(autoId('PhoneCallTable-unlink-job-call-1'))

    expect(await screen.findByText('That call is already invoiced.')).toBeVisible()
  })
})

describe('PhoneCallTable — the link-job dialog', () => {
  it('lists the company jobs, links the picked one and refetches', async () => {
    serveStatusChoices()
    const counter = serveList([call()])
    const jobRequests: string[] = []
    const bodies: unknown[] = []
    server.use(
      http.get('*/api/companies/:companyId/jobs/', ({ params }) => {
        jobRequests.push(String(params.companyId))
        return HttpResponse.json({ results: [companyJob()] })
      }),
      http.post('*/api/crm/phone-calls/:callId/job-link/', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(linkedCall)
      }),
    )
    const { user } = renderWithProviders(<TableOverLiveList />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-job-call-1')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-link-job-call-1'))

    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-dialog')).not.toBeNull())
    await waitFor(() => expect(jobRequests).toEqual(['company-1']))

    await user.click(autoId('PhoneCallTable-job-trigger'))
    await waitFor(() => expect(queryAutoId('PhoneCallTable-job-option-101')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-job-option-101'))

    await user.click(autoId('PhoneCallTable-save-job-link'))
    await waitFor(() => expect(bodies).toEqual([{ job: 'job-1' }]))
    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-dialog')).toBeNull())
    await waitFor(() => expect(counter.gets).toBe(2))
  })

  it('surfaces the backend refusal and keeps the dialog open', async () => {
    serveStatusChoices()
    serveList([call()])
    server.use(
      http.get('*/api/companies/:companyId/jobs/', () =>
        HttpResponse.json({ results: [companyJob()] }),
      ),
      http.post('*/api/crm/phone-calls/:callId/job-link/', () =>
        HttpResponse.json(
          { status: 'error', message: 'That job belongs to another company.' },
          { status: 400 },
        ),
      ),
    )
    const { user } = renderWithProviders(<TableOverLiveList />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-job-call-1')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-link-job-call-1'))
    await waitFor(() => expect(queryAutoId('PhoneCallTable-job-trigger')).not.toBeNull())

    await user.click(autoId('PhoneCallTable-job-trigger'))
    await waitFor(() => expect(queryAutoId('PhoneCallTable-job-option-101')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-job-option-101'))
    await user.click(autoId('PhoneCallTable-save-job-link'))

    expect(await screen.findByText('That job belongs to another company.')).toBeVisible()
    expect(queryAutoId('PhoneCallTable-link-dialog')).not.toBeNull()
  })

  it('closes without writing when cancelled', async () => {
    serveStatusChoices()
    serveList([call()])
    server.use(
      http.get('*/api/companies/:companyId/jobs/', () =>
        HttpResponse.json({ results: [companyJob()] }),
      ),
    )
    const { user } = renderWithProviders(<TableOverLiveList />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-job-call-1')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-link-job-call-1'))
    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-dialog')).not.toBeNull())

    await user.click(autoId('PhoneCallTable-cancel-job-link'))
    await waitFor(() => expect(queryAutoId('PhoneCallTable-link-dialog')).toBeNull())
  })

  it('opens Change on the job the call already holds', async () => {
    serveStatusChoices()
    serveList([linkedCall])
    server.use(
      http.get('*/api/companies/:companyId/jobs/', () =>
        HttpResponse.json({ results: [companyJob()] }),
      ),
    )
    const { user } = renderWithProviders(<TableOverLiveList />)

    await screen.findByText('Job #101')
    await user.click(autoId('PhoneCallTable-change-job-call-1'))

    await waitFor(() => expect(queryAutoId('PhoneCallTable-job-trigger')).not.toBeNull())
    expect(autoId('PhoneCallTable-job-trigger')).toHaveTextContent('#101 - Fabricate frame')
  })
})
