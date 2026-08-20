import { Link } from '@tanstack/react-router'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { LeaveSettingsPage } from './LeaveSettingsPage'

import type { JobOptionOut, LeaveSettingsOut, LeaveTypeOut, XeroPayItemOut } from '@/api'

const SETTINGS = '*/api/timesheets/leave-settings/'
const PAY_ITEMS = '*/api/xero/pay-items/'
const JOBS = '*/api/job/jobs/options/'

const LEAVE_JOB_ID = 'job-annual'
const PAY_ITEM_ID = 'pay-annual'

function leaveType(overrides: Partial<LeaveTypeOut> = {}): LeaveTypeOut {
  return {
    code: 'annual_leave',
    display_name: 'Annual Leave',
    job_id: LEAVE_JOB_ID,
    job_name: 'Annual Leave Job',
    xero_pay_item_id: PAY_ITEM_ID,
    xero_pay_item_name: 'Annual Leave',
    posting_surface: 'leave_api',
    configured: true,
    ...overrides,
  }
}

function settings(types: LeaveTypeOut[] = [leaveType()]): LeaveSettingsOut {
  return { leave_types: types }
}

function payItem(overrides: Partial<XeroPayItemOut> = {}): XeroPayItemOut {
  return {
    created_at: '2026-08-01T00:00:00Z',
    id: PAY_ITEM_ID,
    multiplier: null,
    name: 'Annual Leave',
    updated_at: '2026-08-01T00:00:00Z',
    uses_leave_api: true,
    xero_id: 'xero-annual',
    xero_last_modified: null,
    xero_last_synced: null,
    xero_tenant_id: 'tenant-1',
    ...overrides,
  }
}

function job(overrides: Partial<JobOptionOut> = {}): JobOptionOut {
  return {
    id: LEAVE_JOB_ID,
    job_number: 900,
    name: 'Annual Leave Job',
    company_name: null,
    status: 'special',
    ...overrides,
  }
}

function mockLoad(jobs: JobOptionOut[] = [job()]) {
  server.use(
    http.get(SETTINGS, () => HttpResponse.json(settings())),
    http.get(PAY_ITEMS, () => HttpResponse.json([payItem()])),
    http.get(JOBS, () => HttpResponse.json({ jobs })),
  )
}

const nameField = () => screen.getByLabelText('annual_leave display name')

async function renderPage() {
  // A real Link, so navigating away exercises the router blocker rather than a
  // stubbed navigate that would never reach it.
  const result = renderWithProviders(
    <>
      <LeaveSettingsPage />
      <Link to="/kanban">Leave this page</Link>
    </>,
  )
  await screen.findByLabelText('annual_leave display name')
  return result
}

function autoId(id: string): HTMLElement {
  const el = document.querySelector(`[data-automation-id="${id}"]`)
  if (!(el instanceof HTMLElement)) throw new Error(`missing element ${id}`)
  return el
}
const save = () => autoId('LeaveSettingsPage-save-button')
const cancel = () => autoId('LeaveSettingsPage-cancel-button')

describe('LeaveSettingsPage', () => {
  beforeEach(() => {
    mockLoad()
  })

  it('disables Save until something actually changes', async () => {
    const { user } = await renderPage()
    expect(save()).toBeDisabled()
    expect(cancel()).toBeDisabled()

    await user.type(nameField(), 'X')
    expect(save()).toBeEnabled()
  })

  it('a background refetch does not clobber an unsaved edit', async () => {
    // The regression this page was rewritten for: an effect used to re-hydrate
    // local state from every refetch, silently discarding the admin's typing.
    const { user, queryClient } = await renderPage()
    await user.clear(nameField())
    await user.type(nameField(), 'Holiday Leave')

    server.use(
      http.get(SETTINGS, () =>
        HttpResponse.json(
          settings([leaveType({ display_name: 'Renamed Elsewhere', configured: false })]),
        ),
      ),
    )
    await queryClient.refetchQueries()

    // The refetch really did land — read-only status reflects the new payload…
    expect(await screen.findByText('Needs configuration')).toBeInTheDocument()
    // …while the edit in flight survived it.
    expect(nameField()).toHaveValue('Holiday Leave')
    expect(save()).toBeEnabled()
  })

  it('submits only the rows that changed', async () => {
    const bodies: unknown[] = []
    server.use(
      http.patch(SETTINGS, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(settings([leaveType({ display_name: 'Holiday Leave' })]))
      }),
    )
    const { user } = await renderPage()
    await user.clear(nameField())
    await user.type(nameField(), 'Holiday Leave')
    await user.click(save())

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      leave_types: [
        {
          code: 'annual_leave',
          display_name: 'Holiday Leave',
          job_id: LEAVE_JOB_ID,
          xero_pay_item_id: PAY_ITEM_ID,
        },
      ],
    })
    // The snapshot advanced from the response, so the page is clean again.
    await waitFor(() => expect(save()).toBeDisabled())
  })

  it('a public-holiday edit saves with no pay item, and needs only its Job', async () => {
    // The xero_computed surface has no Xero object to name: the server sends
    // null for it, offers no select, and the save must send null back rather
    // than refusing the row as incomplete — that refusal is what used to
    // strand every batch containing a public-holiday edit.
    const publicHoliday = leaveType({
      code: 'public_holiday',
      display_name: 'Public Holiday',
      job_id: 'job-ph',
      job_name: 'Public Holiday Job',
      xero_pay_item_id: null,
      xero_pay_item_name: null,
      posting_surface: 'xero_computed',
    })
    const bodies: unknown[] = []
    server.use(
      http.get(SETTINGS, () => HttpResponse.json(settings([leaveType(), publicHoliday]))),
      http.get(PAY_ITEMS, () => HttpResponse.json([payItem()])),
      http.get(JOBS, () =>
        HttpResponse.json({
          jobs: [job(), job({ id: 'job-ph', job_number: 901, name: 'Public Holiday Job' })],
        }),
      ),
      http.patch(SETTINGS, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(
          settings([leaveType(), { ...publicHoliday, display_name: 'Stat Day' }]),
        )
      }),
    )
    const { user } = await renderPage()

    const phName = screen.getByLabelText('public_holiday display name')
    await user.clear(phName)
    await user.type(phName, 'Stat Day')
    expect(save()).toBeEnabled()
    await user.click(save())

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      leave_types: [
        {
          code: 'public_holiday',
          display_name: 'Stat Day',
          job_id: 'job-ph',
          xero_pay_item_id: null,
        },
      ],
    })
    await waitFor(() => expect(save()).toBeDisabled())
  })

  it('Cancel restores the loaded values and re-disables Save', async () => {
    const { user } = await renderPage()
    await user.clear(nameField())
    await user.type(nameField(), 'Scratch')
    expect(save()).toBeEnabled()

    await user.click(cancel())
    expect(nameField()).toHaveValue('Annual Leave')
    expect(save()).toBeDisabled()
  })

  it('a failed save keeps the edits and surfaces the server message', async () => {
    server.use(
      http.patch(SETTINGS, () =>
        HttpResponse.json({ detail: 'Annual Leave requires a Xero leave type.' }, { status: 400 }),
      ),
    )
    const { user } = await renderPage()
    await user.clear(nameField())
    await user.type(nameField(), 'Holiday Leave')
    await user.click(save())

    expect(await screen.findByText(/requires a Xero leave type/)).toBeInTheDocument()
    expect(nameField()).toHaveValue('Holiday Leave')
    expect(save()).toBeEnabled()
  })

  it('asks the server for special jobs only, and offers what it returns', async () => {
    // The special-only rule is the server's — the page must not re-implement it
    // client-side, so what it asks for is the assertion that matters.
    const statuses: (string | null)[] = []
    server.use(
      http.get(JOBS, ({ request }) => {
        statuses.push(new URL(request.url).searchParams.get('status'))
        return HttpResponse.json({ jobs: [job()] })
      }),
    )
    const { user } = await renderPage()

    expect(statuses).toEqual(['special'])
    await user.click(autoId('LeaveSettingsPage-job-annual_leave-trigger'))
    expect(autoId('LeaveSettingsPage-job-annual_leave-option-900')).toBeInTheDocument()
  })

  it('asks for confirmation before leaving with unsaved changes, and stays when refused', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { user } = await renderPage()
    await user.clear(nameField())
    await user.type(nameField(), 'Scratch')

    await user.click(screen.getByRole('link', { name: 'Leave this page' }))

    expect(confirm).toHaveBeenCalledWith(
      'You have unsaved changes. Discard them and leave this page?',
    )
    expect(nameField()).toBeInTheDocument()
    confirm.mockRestore()
  })

  it('does not ask when nothing has changed', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { user } = await renderPage()

    await user.click(screen.getByRole('link', { name: 'Leave this page' }))

    expect(confirm).not.toHaveBeenCalled()
    confirm.mockRestore()
  })
})
