import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { TimesheetJobOut } from '@/api'
import { renderWithProviders } from '@/test/render'
import { TimesheetJobPicker } from './TimesheetJobPicker'

const workshopRate = {
  id: 'rate-1',
  labour_subtype: 'subtype-workshop',
  labour_subtype_name: 'Workshop',
  is_workshop: true,
  charge_out_rate: '120.00',
}

function makeJob(overrides: Partial<TimesheetJobOut> = {}): TimesheetJobOut {
  return {
    id: 'job-1',
    job_number: 101,
    name: 'Fabricate frame',
    company_name: 'ABC Carpet Cleaning TEST IGNORE',
    status: 'in_progress',
    labour_rates: [workshopRate],
    has_actual_costset: true,
    leave_type: null,
    estimated_hours: null,
    default_xero_pay_item_id: 'pay-ordinary',
    default_xero_pay_item_name: 'Ordinary Time',
    shop_job: false,
    is_urgent: false,
    ...overrides,
  }
}

const urgentJob = makeJob({ id: 'job-2', job_number: 202, name: 'Emergency gate', is_urgent: true })

async function renderPicker(props: Partial<Parameters<typeof TimesheetJobPicker>[0]> = {}) {
  const onSelect = vi.fn()
  renderWithProviders(
    <TimesheetJobPicker
      automationIdPrefix="SmartTimesheetTable-jobPicker-0"
      jobs={[makeJob(), urgentJob]}
      selected={null}
      disabled={false}
      entrySeq={null}
      gridRow={0}
      onSelect={onSelect}
      {...props}
    />,
  )
  // The test router resolves asynchronously; wait for the mounted trigger.
  await waitFor(() => trigger())
  return { onSelect }
}

function autoId(id: string): HTMLElement {
  const el = document.querySelector(`[data-automation-id="${id}"]`)
  if (!(el instanceof HTMLElement)) throw new Error(`missing element ${id}`)
  return el
}
const trigger = () => autoId('SmartTimesheetTable-jobPicker-0-trigger')
const search = () => autoId('SmartTimesheetTable-jobPicker-0-search')

describe('TimesheetJobPicker', () => {
  it('renders the placeholder trigger with grid attributes', async () => {
    await renderPicker()
    expect(trigger()).toHaveTextContent('Select job…')
    expect(trigger()).toHaveAttribute('data-grid-col', 'jobNumber')
  })

  it('shows the job number and urgent chip when selected', async () => {
    await renderPicker({ selected: urgentJob, entrySeq: 3 })
    expect(trigger()).toHaveTextContent('#202')
    expect(trigger()).toHaveTextContent('!')
    expect(trigger()).toHaveAttribute('data-entry-seq', '3')
  })

  it('opens on click with the search focused, and filters', async () => {
    const user = userEvent.setup()
    await renderPicker()
    await user.click(trigger())
    await waitFor(() => expect(search()).toHaveFocus())
    await user.keyboard('202')
    expect(autoId('SmartTimesheetTable-jobPicker-0-option-202')).toBeInTheDocument()
    expect(
      document.querySelector('[data-automation-id="SmartTimesheetTable-jobPicker-0-option-101"]'),
    ).not.toBeInTheDocument()
  })

  it('marks urgent options with an URGENT chip', async () => {
    const user = userEvent.setup()
    await renderPicker()
    await user.click(trigger())
    expect(autoId('SmartTimesheetTable-jobPicker-0-option-202')).toHaveTextContent('URGENT')
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

  it('Tab picks the highlighted match', async () => {
    const user = userEvent.setup()
    const { onSelect } = await renderPicker()
    await user.click(trigger())
    await user.keyboard('101')
    await user.keyboard('{Tab}')
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect.mock.calls[0]![0].job_number).toBe(101)
  })

  it('arrow keys move the highlight before Enter picks', async () => {
    const user = userEvent.setup()
    const { onSelect } = await renderPicker()
    await user.click(trigger())
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onSelect.mock.calls[0]![0].job_number).toBe(202)
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
    expect(
      document.querySelector('[data-automation-id="SmartTimesheetTable-jobPicker-0-search"]'),
    ).toBeNull()
  })
})
