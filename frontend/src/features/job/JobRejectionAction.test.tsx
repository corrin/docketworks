import { act, screen, waitFor } from '@testing-library/react'
import { useSuspenseQuery } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'

import { getFullJobOptions, jobJobsFinishRetrieveOptions } from '@/api'
import { meQueryOptions } from '@/features/auth'
import { emitConcurrencyRetry } from '@/lib/concurrency/retry-bus'
import { autoId, queryAutoId } from '@/test/auto-id'
import { deferred } from '@/test/deferred'
import { finishPayload, jobDetail } from '@/test/job'
import { seedJobViews } from '@/test/jobViews'
import { mockUser } from '@/test/me'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { JobRejectionAction } from './JobRejectionAction'

const JOB_ID = '0b54b371-4d33-49e7-be29-31bd93bc78cf'
const JOB_URL = `*/api/job/jobs/${JOB_ID}/`
const job = jobDetail({ id: JOB_ID })

function balance(remaining: string) {
  return {
    ...finishPayload,
    summary: { ...finishPayload.summary, remaining_to_invoice_excl_gst: remaining },
  }
}

async function waitForAction() {
  await waitFor(() => expect(autoId('JobView-rejection-action')).toBeInTheDocument())
}

function LiveAction() {
  const { data } = useSuspenseQuery(getFullJobOptions({ path: { job_id: JOB_ID } }))
  return <JobRejectionAction job={data.data.job} />
}

describe('job rejection', () => {
  beforeEach(() => {
    vi.spyOn(toast, 'success').mockImplementation(() => 0)
  })
  afterEach(() => vi.restoreAllMocks())
  it('checks a fresh balance, submits both fields once, and refreshes both job views', async () => {
    mockUser()
    const saved = deferred()
    const bodies: unknown[] = []
    let reads = 0
    server.use(
      http.get(`${JOB_URL}finish/`, () => {
        reads += 1
        return HttpResponse.json(balance('0.00'))
      }),
      http.patch(JOB_URL, async ({ request }) => {
        bodies.push(await request.json())
        await saved.promise
        return HttpResponse.json({ success: true })
      }),
    )
    const { user, queryClient } = renderWithProviders(<JobRejectionAction job={job} />)
    await waitForAction()
    queryClient.setQueryData(
      jobJobsFinishRetrieveOptions({ path: { job_id: JOB_ID } }).queryKey,
      finishPayload,
    )
    const keys = seedJobViews(queryClient, JOB_ID)

    await user.dblClick(autoId('JobView-rejection-action'))
    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(autoId('JobView-rejection-action')).toBeDisabled()
    expect(autoId('JobView-rejection-action')).toHaveTextContent('Saving…')
    // With nothing uninvoiced there is nothing to decide, so no dialog opens.
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(toast.success).not.toHaveBeenCalled()
    expect(reads).toBe(1)
    expect(bodies[0]).toMatchObject({
      fields: ['job_status', 'rejected_flag'],
      before: { job_status: 'draft', rejected_flag: false },
      after: { job_status: 'archived', rejected_flag: true },
    })
    saved.resolve()
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Job rejected and moved to Archived'),
    )
    expect(queryClient.getQueryState(keys.job)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(keys.timeline)?.isInvalidated).toBe(true)
  })

  it('allows cancelling the warning and reads the balance again on the next attempt', async () => {
    mockUser()
    let reads = 0
    const bodies: unknown[] = []
    server.use(
      http.get(`${JOB_URL}finish/`, () =>
        HttpResponse.json(balance(++reads === 1 ? '1000.00' : '250.00')),
      ),
      http.patch(JOB_URL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ success: true })
      }),
    )
    const { user } = renderWithProviders(<JobRejectionAction job={job} />)
    await waitForAction()
    await user.click(autoId('JobView-rejection-action'))
    await waitFor(() =>
      expect(autoId('JobView-rejection-warning')).toHaveTextContent('$1,000.00 excluding GST'),
    )
    await user.click(autoId('JobView-rejection-cancel'))
    expect(bodies).toHaveLength(0)
    await user.click(autoId('JobView-rejection-action'))
    await waitFor(() =>
      expect(autoId('JobView-rejection-warning')).toHaveTextContent('$250.00 excluding GST'),
    )
    await user.click(autoId('JobView-rejection-confirm'))
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Job rejected and moved to Archived'),
    )
    expect(bodies).toHaveLength(1)
  })

  it('confirms reopening to Draft and lets the user cancel it', async () => {
    mockUser()
    const bodies: unknown[] = []
    server.use(
      http.patch(JOB_URL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ success: true })
      }),
    )
    const { user } = renderWithProviders(
      <JobRejectionAction
        job={jobDetail({ id: JOB_ID, job_status: 'archived', rejected_flag: true })}
      />,
    )
    await waitForAction()
    expect(autoId('JobView-rejection-action')).toHaveTextContent('Reopen job')
    await user.click(autoId('JobView-rejection-action'))
    await screen.findByText('Clearing rejection moves this job back to Draft.')
    await user.click(autoId('JobView-rejection-cancel'))
    expect(bodies).toHaveLength(0)
    await user.click(autoId('JobView-rejection-action'))
    await user.click(autoId('JobView-rejection-confirm'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Job reopened in Draft'))
    expect(bodies[0]).toMatchObject({
      before: { job_status: 'archived', rejected_flag: true },
      after: { job_status: 'draft', rejected_flag: false },
    })
  })

  it('reopens after a rejection refetch and repeated cancellation without remounting', async () => {
    mockUser()
    let current = job
    let writes = 0
    server.use(
      http.get(JOB_URL, () => HttpResponse.json({ data: { job: current } })),
      http.get(`${JOB_URL}finish/`, () => HttpResponse.json(balance('0.00'))),
      http.patch(JOB_URL, () => {
        writes += 1
        current = {
          ...current,
          rejected_flag: writes === 1,
          job_status: writes === 1 ? 'archived' : 'draft',
        }
        return HttpResponse.json({ success: true })
      }),
    )
    const { user } = renderWithProviders(<LiveAction />)
    await waitForAction()
    await user.click(autoId('JobView-rejection-action'))
    await waitFor(() => expect(autoId('JobView-rejection-action')).toHaveTextContent('Reopen job'))
    const openAndCancel = async () => {
      await user.click(autoId('JobView-rejection-action'))
      await waitFor(() =>
        expect(autoId('JobView-rejection-confirm')).toHaveTextContent('Reopen in Draft'),
      )
      await user.click(autoId('JobView-rejection-cancel'))
      await waitFor(() => expect(queryAutoId('JobView-rejection-confirm')).toBeNull())
      expect(autoId('JobView-rejection-action')).toHaveFocus()
    }
    await openAndCancel()
    await openAndCancel()
    await openAndCancel()
    expect(writes).toBe(1)
    await user.click(autoId('JobView-rejection-action'))
    await user.click(autoId('JobView-rejection-confirm'))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Job reopened in Draft'))
    expect(writes).toBe(2)
    expect(autoId('JobView-rejection-action')).toHaveTextContent('Reject job')
  })

  it('blocks submission on a failed balance read and offers a working retry', async () => {
    mockUser()
    let reads = 0
    let writes = 0
    server.use(
      http.get(`${JOB_URL}finish/`, () =>
        ++reads === 1
          ? HttpResponse.json({ detail: 'Balance unavailable' }, { status: 503 })
          : HttpResponse.json(balance('0.00')),
      ),
      http.patch(JOB_URL, () => {
        writes += 1
        return HttpResponse.json({ success: true })
      }),
    )
    const { user } = renderWithProviders(<JobRejectionAction job={job} />)
    await waitForAction()
    await user.click(autoId('JobView-rejection-action'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Balance unavailable')
    expect(writes).toBe(0)
    await user.click(autoId('JobView-rejection-retry'))
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Job rejected and moved to Archived'),
    )
    expect(reads).toBe(2)
    expect(writes).toBe(1)
  })

  it('retains a save failure and rechecks the balance before retrying', async () => {
    mockUser()
    let reads = 0
    let writes = 0
    server.use(
      http.get(`${JOB_URL}finish/`, () => {
        reads += 1
        return HttpResponse.json(balance('0.00'))
      }),
      http.patch(JOB_URL, () =>
        ++writes === 1
          ? HttpResponse.json({ detail: 'Save refused' }, { status: 400 })
          : HttpResponse.json({ success: true }),
      ),
    )
    const { user } = renderWithProviders(<JobRejectionAction job={job} />)
    await waitForAction()
    await user.click(autoId('JobView-rejection-action'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Save refused')
    expect(toast.success).not.toHaveBeenCalled()
    await user.click(autoId('JobView-rejection-retry'))
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('Job rejected and moved to Archived'),
    )
    expect(reads).toBe(2)
    expect(writes).toBe(2)
  })

  it.each([true, false])(
    'rechecks and confirms the new balance on conflict retry (confirm=%s)',
    async (confirm) => {
      mockUser()
      let reads = 0
      const bodies: unknown[] = []
      server.use(
        http.get(`${JOB_URL}finish/`, () =>
          HttpResponse.json(balance(++reads === 1 ? '0.00' : '250.00')),
        ),
        http.get(JOB_URL, () =>
          HttpResponse.json({ data: { job: { ...job, job_status: 'in_progress' } } }),
        ),
        http.patch(JOB_URL, async ({ request }) => {
          bodies.push(await request.json())
          return bodies.length === 1
            ? HttpResponse.json({ detail: 'Changed elsewhere' }, { status: 412 })
            : HttpResponse.json({ success: true })
        }),
      )
      const { user } = renderWithProviders(<JobRejectionAction job={job} />)
      await waitForAction()
      await user.click(autoId('JobView-rejection-action'))
      await waitFor(() => {
        expect(bodies).toHaveLength(1)
        expect(autoId('JobView-rejection-action')).toBeEnabled()
      })
      act(() => emitConcurrencyRetry({ kind: 'job', id: JOB_ID }))
      await waitFor(() =>
        expect(autoId('JobView-rejection-warning')).toHaveTextContent('$250.00 excluding GST'),
      )
      expect(bodies).toHaveLength(1)
      if (!confirm) {
        await user.click(autoId('JobView-rejection-cancel'))
        act(() => emitConcurrencyRetry({ kind: 'job', id: JOB_ID }))
        expect(queryAutoId('JobView-rejection-confirm')).toBeNull()
        expect(bodies).toHaveLength(1)
        return
      }
      await user.click(autoId('JobView-rejection-confirm'))
      await waitFor(() =>
        expect(toast.success).toHaveBeenCalledWith('Job rejected and moved to Archived'),
      )
      expect(bodies[1]).toMatchObject({
        before: { job_status: 'in_progress', rejected_flag: false },
        after: { job_status: 'archived', rejected_flag: true },
      })
    },
  )

  it('hides the mutation action from workshop staff', async () => {
    mockUser({ is_office_staff: false })
    const { queryClient } = renderWithProviders(<JobRejectionAction job={job} />)
    await waitFor(() =>
      expect(queryClient.getQueryData(meQueryOptions().queryKey)).toMatchObject({
        is_office_staff: false,
      }),
    )
    expect(queryAutoId('JobView-rejection-action')).toBeNull()
  })
})
