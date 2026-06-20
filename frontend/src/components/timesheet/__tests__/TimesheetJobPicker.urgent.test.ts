import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import type { z } from 'zod'
import { schemas } from '@/api/generated/api'
import TimesheetJobPicker from '../TimesheetJobPicker.vue'

type Job = z.infer<typeof schemas.ModernTimesheetJob>

function makeJob(overrides: Partial<Job>): Job {
  return {
    id: overrides.id ?? '11111111-1111-1111-1111-111111111111',
    job_number: overrides.job_number ?? 100,
    name: overrides.name ?? 'Test Job',
    client_name: overrides.client_name ?? 'Acme',
    status: overrides.status ?? 'in_progress',
    labour_rates: overrides.labour_rates ?? [
      {
        labour_subtype: 'sub-workshop',
        labour_subtype_name: 'Workshop',
        charge_out_rate: 100,
        is_workshop: true,
      } as unknown as Job['labour_rates'][number],
    ],
    has_actual_costset: overrides.has_actual_costset ?? true,
    leave_type: overrides.leave_type ?? null,
    estimated_hours: overrides.estimated_hours ?? null,
    default_xero_pay_item_id:
      overrides.default_xero_pay_item_id ?? '22222222-2222-2222-2222-222222222222',
    default_xero_pay_item_name: overrides.default_xero_pay_item_name ?? 'Ordinary Hours',
    shop_job: overrides.shop_job ?? false,
    is_urgent: overrides.is_urgent ?? false,
  } as Job
}

function mountPicker(jobs: Job[], modelValue: number | null = null) {
  return mount(TimesheetJobPicker, {
    props: {
      modelValue,
      jobs,
      automationIdPrefix: 'PickerUnderTest',
    },
    global: {
      stubs: {
        Popover: { template: '<div><slot /></div>' },
        PopoverTrigger: { template: '<div><slot /></div>' },
        PopoverContent: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('TimesheetJobPicker urgent indicators', () => {
  enableAutoUnmount(afterEach)

  it('marks the selected urgent job in the trigger', () => {
    const urgentJob = makeJob({ job_number: 123, is_urgent: true })
    const wrapper = mountPicker([urgentJob], urgentJob.job_number)

    const trigger = wrapper.get('[data-automation-id="PickerUnderTest-trigger"]')
    expect(trigger.text()).toContain('#123')
    expect(trigger.text()).toContain('!')
  })

  it('shows the URGENT option badge only for urgent jobs and emits the selected job', async () => {
    const urgentJob = makeJob({ job_number: 123, is_urgent: true, name: 'Hot Job' })
    const regularJob = makeJob({
      id: '33333333-3333-3333-3333-333333333333',
      job_number: 456,
      is_urgent: false,
      name: 'Regular Job',
    })
    const wrapper = mountPicker([urgentJob, regularJob])

    const urgentOption = wrapper.get('[data-automation-id="PickerUnderTest-option-123"]')
    const regularOption = wrapper.get('[data-automation-id="PickerUnderTest-option-456"]')

    expect(urgentOption.text()).toContain('URGENT')
    expect(regularOption.text()).not.toContain('URGENT')

    await urgentOption.trigger('click')

    expect(wrapper.emitted('select')).toEqual([[urgentJob]])
  })
})
