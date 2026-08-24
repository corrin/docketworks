import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import type { CompanySearchResult, PhoneCallRecordOut } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { PhoneCallsPage } from './PhoneCallsPage'

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

const unmatchedCall = call({
  id: 'call-2',
  company: null,
  company_name: '',
  person_name: '',
})

function company(overrides: Partial<CompanySearchResult> = {}): CompanySearchResult {
  return {
    address: '1 Sample Street',
    allow_jobs: true,
    email: 'accounts@example.com',
    id: 'company-9',
    is_account_customer: true,
    is_supplier: false,
    last_invoice_date: null,
    name: 'Beta Fabrication',
    phone: '03 555 0000',
    total_spend: 0,
    xero_contact_id: 'xero-9',
    ...overrides,
  }
}

/** Records every list request's query string and answers with one page. */
function serveList(rows: PhoneCallRecordOut[] = [call()]): { urls: URL[] } {
  const seen: { urls: URL[] } = { urls: [] }
  server.use(
    http.get('*/api/crm/phone-calls/', ({ request }) => {
      seen.urls.push(new URL(request.url))
      return HttpResponse.json({
        count: rows.length,
        page: 1,
        page_size: 50,
        results: rows,
        total_pages: 1,
      })
    }),
  )
  return seen
}

function lastQuery(seen: { urls: URL[] }): Record<string, string> {
  const last = seen.urls.at(-1)
  if (last === undefined) throw new Error('the list was never requested')
  return Object.fromEntries(last.searchParams.entries())
}

describe('PhoneCallsPage — the queue tabs', () => {
  it('opens on Recent Calls, asking for every call', async () => {
    const seen = serveList()
    renderWithProviders(<PhoneCallsPage />)

    // Both the tab and the queue heading name the queue.
    expect(await screen.findAllByText('Recent Calls')).toHaveLength(2)
    await waitFor(() => expect(seen.urls).toHaveLength(1))
    expect(lastQuery(seen)).toEqual({ company_match: 'all', job_link: 'all', page: '1' })
  })

  it('asks the unmatched queue for calls with no company', async () => {
    const seen = serveList()
    const { user } = renderWithProviders(<PhoneCallsPage />)
    await waitFor(() => expect(seen.urls).toHaveLength(1))

    await user.click(autoId('PhoneCallsPage-tab-unmatched'))

    await waitFor(() => expect(lastQuery(seen)).toEqual({ company_match: 'unmatched', page: '1' }))
    expect(screen.getByText('Unmatched Calls')).toBeVisible()
  })

  it('asks the unlinked queue for matched calls with no job', async () => {
    const seen = serveList()
    const { user } = renderWithProviders(<PhoneCallsPage />)
    await waitFor(() => expect(seen.urls).toHaveLength(1))

    await user.click(autoId('PhoneCallsPage-tab-unlinked'))

    await waitFor(() =>
      expect(lastQuery(seen)).toEqual({
        company_match: 'matched',
        job_link: 'unlinked',
        page: '1',
      }),
    )
    expect(screen.getByText('Matched Calls Needing Job Link')).toBeVisible()
  })
})

describe('PhoneCallsPage — the filters', () => {
  it('searches live after the typing pause, not per keystroke', async () => {
    const seen = serveList()
    const { user } = renderWithProviders(<PhoneCallsPage />)
    await waitFor(() => expect(seen.urls).toHaveLength(1))

    await user.type(autoId('PhoneCallsPage-search'), 'alex')

    // The whole sequence, not a snapshot taken mid-debounce: one request for
    // the settled term and none for 'a', 'al', 'ale'.
    await waitFor(() =>
      expect(seen.urls.map((url) => url.searchParams.get('q'))).toEqual([null, 'alex']),
    )
  })

  it('sends the direction and recording filters as soon as they are chosen', async () => {
    const seen = serveList()
    const { user } = renderWithProviders(<PhoneCallsPage />)
    await waitFor(() => expect(seen.urls).toHaveLength(1))

    await user.selectOptions(autoId('PhoneCallsPage-direction'), 'outbound')
    await waitFor(() => expect(lastQuery(seen).direction).toBe('outbound'))

    await user.click(autoId('PhoneCallsPage-with-recording'))
    await waitFor(() => expect(lastQuery(seen).has_recording).toBe('true'))
  })
})

describe('PhoneCallsPage — the rows', () => {
  it('refetches the visible page on Refresh', async () => {
    const seen = serveList()
    const { user } = renderWithProviders(<PhoneCallsPage />)
    await waitFor(() => expect(seen.urls).toHaveLength(1))

    await user.click(autoId('PhoneCallsPage-refresh'))

    await waitFor(() => expect(seen.urls).toHaveLength(2))
    expect(lastQuery(seen).page).toBe('1')
  })

  it('appends the next page on Load more and stops at the last page', async () => {
    const pages: (string | null)[] = []
    server.use(
      http.get('*/api/crm/phone-calls/', ({ request }) => {
        const page = new URL(request.url).searchParams.get('page')
        pages.push(page)
        if (page === '2') {
          return HttpResponse.json({
            count: 2,
            page: 2,
            page_size: 1,
            results: [call({ id: 'call-3', company_name: 'Gamma Joinery' })],
            total_pages: 2,
          })
        }
        return HttpResponse.json({
          count: 2,
          page: 1,
          page_size: 1,
          results: [call()],
          total_pages: 2,
        })
      }),
    )
    const { user } = renderWithProviders(<PhoneCallsPage />)

    expect(await screen.findByText('Alpha Engineering')).toBeVisible()
    expect(screen.getByText('Showing 1 of 2 calls')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Load more' }))

    expect(await screen.findByText('Gamma Joinery')).toBeVisible()
    expect(screen.getByText('Alpha Engineering')).toBeVisible()
    expect(screen.getByText('Showing 2 of 2 calls')).toBeVisible()
    expect(pages).toEqual(['1', '2'])
  })

  it('keeps the rows and offers a retry when a background refresh fails', async () => {
    let calls = 0
    server.use(
      http.get('*/api/crm/phone-calls/', () => {
        calls += 1
        if (calls === 2) return HttpResponse.json({ detail: 'boom' }, { status: 500 })
        return HttpResponse.json({
          count: 1,
          page: 1,
          page_size: 50,
          results: [call()],
          total_pages: 1,
        })
      }),
    )
    const { user, queryClient } = renderWithProviders(<PhoneCallsPage />)
    await screen.findByText('Alpha Engineering')

    await queryClient.refetchQueries()
    expect(await screen.findByText('Refresh failed — showing the last loaded rows.')).toBeVisible()
    expect(screen.getByText('Alpha Engineering')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(screen.queryByText('Refresh failed — showing the last loaded rows.')).toBeNull(),
    )
  })
})

describe('PhoneCallsPage — assigning a number', () => {
  it('claims the number for a company with no person, then refetches', async () => {
    const seen = serveList([unmatchedCall])
    const bodies: unknown[] = []
    server.use(
      http.get('*/api/companies/search/', () =>
        HttpResponse.json({
          count: 1,
          page: 1,
          page_size: 50,
          results: [company()],
          total_pages: 1,
        }),
      ),
      http.get('*/api/companies/:companyId/people/', () => HttpResponse.json([])),
      http.post('*/api/crm/phone-calls/:callId/assign-number/', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(call({ id: 'call-2' }))
      }),
    )
    const { user } = renderWithProviders(<PhoneCallsPage />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-assign-number-call-2')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-assign-number-call-2'))
    expect(autoId('PhoneCallsPage-assign-panel')).toBeVisible()

    await user.type(autoId('CompanyLookup-input'), 'beta')
    await waitFor(() => expect(queryAutoId('CompanyLookup-option-company-9')).not.toBeNull())
    await user.click(autoId('CompanyLookup-option-company-9'))

    await user.type(autoId('PhoneCallsPage-assign-label'), 'Reception')
    await user.click(autoId('PhoneCallsPage-assign-primary'))
    const requestsBeforeAssign = seen.urls.length
    await user.click(autoId('PhoneCallsPage-assign-submit'))

    await waitFor(() =>
      // person is an explicit null, never an omitted key or a blank string.
      expect(bodies).toEqual([
        { company: 'company-9', person: null, is_primary: true, label: 'Reception' },
      ]),
    )
    await waitFor(() => expect(queryAutoId('PhoneCallsPage-assign-panel')).toBeNull())
    await waitFor(() => expect(seen.urls.length).toBeGreaterThan(requestsBeforeAssign))
  })

  it('sends a null label when the box is left blank', async () => {
    serveList([unmatchedCall])
    const bodies: unknown[] = []
    server.use(
      http.get('*/api/companies/search/', () =>
        HttpResponse.json({
          count: 1,
          page: 1,
          page_size: 50,
          results: [company()],
          total_pages: 1,
        }),
      ),
      http.get('*/api/companies/:companyId/people/', () => HttpResponse.json([])),
      http.post('*/api/crm/phone-calls/:callId/assign-number/', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(call({ id: 'call-2' }))
      }),
    )
    const { user } = renderWithProviders(<PhoneCallsPage />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-assign-number-call-2')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-assign-number-call-2'))
    await user.type(autoId('CompanyLookup-input'), 'beta')
    await waitFor(() => expect(queryAutoId('CompanyLookup-option-company-9')).not.toBeNull())
    await user.click(autoId('CompanyLookup-option-company-9'))
    await user.click(autoId('PhoneCallsPage-assign-submit'))

    await waitFor(() =>
      expect(bodies).toEqual([
        { company: 'company-9', person: null, is_primary: false, label: null },
      ]),
    )
  })

  it('starts the panel empty when it is opened on a second call', async () => {
    serveList([
      unmatchedCall,
      call({ id: 'call-4', company: null, company_name: '', person_name: '' }),
    ])
    server.use(
      http.get('*/api/companies/search/', () =>
        HttpResponse.json({
          count: 1,
          page: 1,
          page_size: 50,
          results: [company()],
          total_pages: 1,
        }),
      ),
      http.get('*/api/companies/:companyId/people/', () => HttpResponse.json([])),
    )
    const { user } = renderWithProviders(<PhoneCallsPage />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-assign-number-call-2')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-assign-number-call-2'))
    await user.type(autoId('CompanyLookup-input'), 'beta')
    await waitFor(() => expect(queryAutoId('CompanyLookup-option-company-9')).not.toBeNull())
    await user.click(autoId('CompanyLookup-option-company-9'))
    await user.type(autoId('PhoneCallsPage-assign-label'), 'Reception')
    expect(autoId('CompanyLookup-input')).toHaveValue('Beta Fabrication')

    // Carrying the first call's company across would let one click write the
    // second call's number to the first call's company.
    await user.click(autoId('PhoneCallTable-assign-number-call-4'))

    expect(autoId('CompanyLookup-input')).toHaveValue('')
    expect(autoId('PhoneCallsPage-assign-label')).toHaveValue('')
    expect(autoId('PhoneCallsPage-assign-submit')).toBeDisabled()
  })

  it('closes the panel without writing when cancelled', async () => {
    serveList([unmatchedCall])
    const { user } = renderWithProviders(<PhoneCallsPage />)

    await waitFor(() => expect(queryAutoId('PhoneCallTable-assign-number-call-2')).not.toBeNull())
    await user.click(autoId('PhoneCallTable-assign-number-call-2'))
    expect(autoId('PhoneCallsPage-assign-panel')).toBeVisible()

    await user.click(autoId('PhoneCallsPage-assign-cancel'))
    expect(queryAutoId('PhoneCallsPage-assign-panel')).toBeNull()
  })
})
