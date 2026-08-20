import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { autoId } from '@/test/auto-id'
import { JobPicker, type JobPickerOption } from './JobPicker'

interface TestJob extends JobPickerOption {
  is_urgent: boolean
}

function makeJob(overrides: Partial<TestJob> = {}): TestJob {
  return {
    id: 'job-1',
    job_number: 101,
    name: 'Fabricate frame',
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    status: 'in_progress',
    is_urgent: false,
    ...overrides,
  }
}

const urgentJob = makeJob({ id: 'job-2', job_number: 202, name: 'Emergency gate', is_urgent: true })

const PREFIX = 'SmartTimesheetTable-jobPicker-0'

const trigger = () => autoId(`${PREFIX}-trigger`)
const search = () => autoId(`${PREFIX}-search`)
const option = (jobNumber: number) => `${PREFIX}-option-${jobNumber}`

async function renderPicker(props: Partial<Parameters<typeof JobPicker<TestJob>>[0]> = {}) {
  const onSelect = vi.fn()
  renderWithProviders(
    <JobPicker
      automationIdPrefix={PREFIX}
      ariaLabel="Job for row 1"
      jobs={[makeJob(), urgentJob]}
      selected={null}
      disabled={false}
      loading={false}
      placeholder="Select job…"
      triggerLabel={(job) => (job === null ? '' : `#${job.job_number}`)}
      renderTriggerBadge={(job) => (job.is_urgent ? <span>!</span> : null)}
      renderOptionDetail={(job) => (job.is_urgent ? <span>URGENT</span> : null)}
      typedSearchLimit={15}
      commitOnTab
      entrySeq={null}
      onSelect={onSelect}
      {...props}
    />,
  )
  // The test router resolves asynchronously; wait for the mounted trigger.
  await waitFor(() => trigger())
  return { onSelect }
}

describe('JobPicker', () => {
  it('renders the placeholder trigger, carrying the entry-seq the keyboard spec binds by', async () => {
    await renderPicker({ entrySeq: 3 })
    expect(trigger()).toHaveTextContent('Select job…')
    expect(trigger()).toHaveAttribute('data-entry-seq', '3')
  })

  it('shows the job number and urgent chip when selected', async () => {
    await renderPicker({ selected: urgentJob })
    expect(trigger()).toHaveTextContent('#202')
    expect(trigger()).toHaveTextContent('!')
  })

  it('opens on click with the search focused, and filters', async () => {
    const user = userEvent.setup()
    await renderPicker()
    await user.click(trigger())
    await waitFor(() => expect(search()).toHaveFocus())
    await user.keyboard('202')
    expect(autoId(option(202))).toBeInTheDocument()
    expect(document.querySelector(`[data-automation-id="${option(101)}"]`)).not.toBeInTheDocument()
  })

  it('matches on name and on company, not only on number', async () => {
    const user = userEvent.setup()
    await renderPicker()
    await user.click(trigger())
    await user.keyboard('emergency')
    expect(autoId(option(202))).toBeInTheDocument()
    await user.clear(search())
    await user.keyboard('carpet')
    expect(autoId(option(101))).toBeInTheDocument()
    expect(autoId(option(202))).toBeInTheDocument()
  })

  it('marks urgent options through the caller-supplied detail', async () => {
    const user = userEvent.setup()
    await renderPicker()
    await user.click(trigger())
    expect(autoId(option(202))).toHaveTextContent('URGENT')
  })

  it('Enter picks the highlighted match', async () => {
    const user = userEvent.setup()
    const { onSelect } = await renderPicker()
    await user.click(trigger())
    await user.keyboard('202')
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]![0].job_number).toBe(202)
  })

  it('Tab picks the highlighted match when the grid commits on Tab', async () => {
    const user = userEvent.setup()
    const { onSelect } = await renderPicker()
    await user.click(trigger())
    await user.keyboard('101')
    await user.keyboard('{Tab}')
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]![0].job_number).toBe(101)
  })

  it('Tab picks NOTHING where the grid does not commit on Tab', async () => {
    // The guard on the PO grid: there Tab is plain focus movement, and
    // committing would bind the first listed job to a cell only tabbed through.
    const user = userEvent.setup()
    const { onSelect } = await renderPicker({ commitOnTab: false })
    await user.click(trigger())
    await user.keyboard('101')
    await user.keyboard('{Tab}')
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('arrow keys move the highlight before Enter picks', async () => {
    const user = userEvent.setup()
    const { onSelect } = await renderPicker()
    await user.click(trigger())
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onSelect.mock.calls[0]![0].job_number).toBe(202)
  })

  it('caps a typed search but never the blank list', async () => {
    const user = userEvent.setup()
    const many = Array.from({ length: 5 }, (_, index) =>
      makeJob({ id: `job-${index}`, job_number: 300 + index, name: `Bracket ${index}` }),
    )
    await renderPicker({ jobs: many, typedSearchLimit: 2 })
    await user.click(trigger())
    expect(document.querySelectorAll(`[data-automation-id^="${PREFIX}-option-"]`)).toHaveLength(5)
    await user.keyboard('bracket')
    expect(document.querySelectorAll(`[data-automation-id^="${PREFIX}-option-"]`)).toHaveLength(2)
  })

  it('shows the bound label even when the job is no longer offered', async () => {
    // A PO line can hold a job that has since been archived out of the list.
    await renderPicker({ jobs: [], selected: null, triggerLabel: () => '97391 - Gate' })
    expect(trigger()).toHaveTextContent('97391 - Gate')
  })

  it('says jobs are loading rather than showing an empty catalogue', async () => {
    const user = userEvent.setup()
    await renderPicker({ jobs: [], loading: true })
    await user.click(trigger())
    expect(autoId(`${PREFIX}-list`)).toHaveTextContent('Jobs are loading…')
  })

  it('opens automatically when an empty enabled trigger receives focus', async () => {
    await renderPicker()
    trigger().focus()
    await waitFor(() => expect(search()).toBeInTheDocument())
  })

  it('never opens when disabled', async () => {
    await renderPicker({ disabled: true })
    expect(trigger()).toBeDisabled()
    trigger().focus()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(document.querySelector(`[data-automation-id="${PREFIX}-search"]`)).toBeNull()
  })

  it('appends background results below the local ones, behind a divider', async () => {
    const user = userEvent.setup()
    const archived = makeJob({
      id: 'job-old',
      job_number: 303,
      name: 'Gate for archive',
      status: 'archived',
    })
    await renderPicker({
      jobs: [makeJob({ job_number: 101, name: 'Gate frame' })],
      useJobSearch: () => ({ jobs: [archived], isFetching: false, isError: false }),
    })
    await user.click(trigger())
    await user.keyboard('gate')

    const ids = [...document.querySelectorAll(`[data-automation-id^="${PREFIX}-option-"]`)].map(
      (el) => el.getAttribute('data-automation-id'),
    )
    expect(ids).toEqual([option(101), option(303)])
    expect(autoId(`${PREFIX}-other-jobs`)).toBeInTheDocument()
  })

  it('does not renumber the local block when background results arrive', async () => {
    // The hazard: a response landing mid-keystroke resetting the highlight
    // the user has already arrowed onto.
    const user = userEvent.setup()
    const archived = makeJob({ id: 'c', job_number: 303, name: 'Gate archived' })
    // Keyed on the term, so results arrive when the real debounce elapses —
    // which is the sequence being tested: highlight set first, response after.
    const { onSelect } = await renderPicker({
      jobs: [
        makeJob({ job_number: 101, name: 'Gate one' }),
        makeJob({ id: 'b', job_number: 102, name: 'Gate two' }),
      ],
      typedSearchLimit: null,
      useJobSearch: (term: string) => ({
        jobs: term === '' ? [] : [archived],
        isFetching: false,
        isError: false,
      }),
    })
    await user.click(trigger())
    await user.keyboard('gate')
    await user.keyboard('{ArrowDown}')
    expect(document.querySelector(`[data-automation-id="${option(303)}"]`)).toBeNull()

    // The background response lands; the user's highlight must survive it.
    await waitFor(() => expect(autoId(option(303))).toBeInTheDocument())

    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]![0].job_number).toBe(102)
  })

  it('reports a failed background search without blanking the local results', async () => {
    const user = userEvent.setup()
    await renderPicker({
      useJobSearch: () => ({ jobs: [], isFetching: false, isError: true }),
    })
    await user.click(trigger())
    await user.keyboard('fab')

    expect(autoId(`${PREFIX}-search-failed`)).toBeInTheDocument()
    expect(autoId(option(101))).toBeInTheDocument()
  })

  it('says it is still searching rather than claiming nothing matched', async () => {
    const user = userEvent.setup()
    await renderPicker({
      jobs: [],
      useJobSearch: () => ({ jobs: [], isFetching: true, isError: false }),
    })
    await user.click(trigger())
    await user.keyboard('gate')

    expect(autoId(`${PREFIX}-searching`)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('No jobs found')
  })

  it('spends no request on a term below the minimum', async () => {
    const user = userEvent.setup()
    const terms: string[] = []
    await renderPicker({
      useJobSearch: (term: string) => {
        terms.push(term)
        return { jobs: [], isFetching: false, isError: false }
      },
    })
    await user.click(trigger())
    await user.keyboard('fa')
    await new Promise((resolve) => setTimeout(resolve, 400))

    // Every call saw the blank term, so the caller's query stayed disabled.
    expect(terms.every((term) => term === '')).toBe(true)
  })

  it('closes on Escape without picking anything', async () => {
    const user = userEvent.setup()
    const { onSelect } = await renderPicker()
    await user.click(trigger())
    await user.keyboard('101')
    await user.keyboard('{Escape}')
    expect(onSelect).not.toHaveBeenCalled()
    await waitFor(() =>
      expect(document.querySelector(`[data-automation-id="${PREFIX}-search"]`)).toBeNull(),
    )
  })
})
