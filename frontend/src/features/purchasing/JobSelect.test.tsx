import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { JobForPurchasing } from '@/api'
import { renderWithProviders } from '@/test/render'
import { JobSelect } from './JobSelect'

function job(overrides: Partial<JobForPurchasing>): JobForPurchasing {
  const base = {
    id: 'job-1',
    job_number: 100,
    name: 'Handrail',
    company_name: 'ABC',
    status: 'draft',
    is_stock_holding: false,
    ...overrides,
  }
  return { ...base, job_display_name: `${base.job_number} - ${base.name}` }
}

const jobs = [job({ id: 'a', job_number: 100, name: 'Handrail' })]

describe('JobSelect', () => {
  it('reverts to the bound label after blurring without picking anything', async () => {
    const { user } = renderWithProviders(
      <JobSelect
        jobNumber={200}
        jobName="Gate"
        jobs={jobs}
        jobsLoading={false}
        onPickJob={vi.fn()}
      />,
    )
    const input = await screen.findByPlaceholderText('Assign job...')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'handrail')
    expect(input).toHaveValue('handrail')

    await user.click(document.body)
    await vi.waitFor(() => expect(input).toHaveValue('200 - Gate'))
  })

  it('reverts to the bound label on Escape without picking anything', async () => {
    const { user } = renderWithProviders(
      <JobSelect
        jobNumber={200}
        jobName="Gate"
        jobs={jobs}
        jobsLoading={false}
        onPickJob={vi.fn()}
      />,
    )
    const input = await screen.findByPlaceholderText('Assign job...')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'handrail')

    await user.keyboard('{Escape}')
    expect(input).toHaveValue('200 - Gate')
  })

  it('selects the arrow-key-active option on Enter', async () => {
    const onPickJob = vi.fn()
    const { user } = renderWithProviders(
      <JobSelect
        jobNumber={null}
        jobName={null}
        jobs={jobs}
        jobsLoading={false}
        onPickJob={onPickJob}
      />,
    )
    const input = await screen.findByPlaceholderText('Assign job...')
    await user.click(input)
    await screen.findByRole('option', { name: /Handrail/ })

    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Enter}')

    expect(onPickJob).toHaveBeenCalledWith(jobs[0])
  })
})
