import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

const { updateJobLabourRatesMock, getJobLabourRatesMock, toastErrorMock } = vi.hoisted(() => ({
  updateJobLabourRatesMock: vi.fn(),
  getJobLabourRatesMock: vi.fn(),
  toastErrorMock: vi.fn(),
}))

vi.mock('@/composables/useJobAutosave', () => ({
  createJobAutosave: () => ({
    queueChange: vi.fn(),
    queueChanges: vi.fn(),
    flush: vi.fn(),
    cancel: vi.fn(),
    isSaving: { value: false },
    lastSavedAt: { value: null },
    error: { value: null },
    pendingKeys: { value: new Set() },
    inFlightToken: { value: 0 },
    hasPending: () => false,
    getPendingPatch: () => ({}),
    onBeforeUnloadBind: vi.fn(),
    onBeforeUnloadUnbind: vi.fn(),
    onVisibilityBind: vi.fn(),
    onVisibilityUnbind: vi.fn(),
    onRouteLeaveBind: vi.fn(() => vi.fn()),
    clearStatus: vi.fn(),
  }),
}))

vi.mock('@/stores/jobs', () => ({
  useJobsStore: () => ({
    headersById: {},
    conflictReloadAtById: {},
    loadBasicInfo: vi.fn().mockResolvedValue({
      description: '',
      delivery_date: '',
      order_number: '',
      notes: '',
    }),
    getJobById: vi.fn(() => null),
    getBasicInfoById: vi.fn(() => null),
    updateDetailedJob: vi.fn(),
    updateJobHeader: vi.fn(),
    patchHeader: vi.fn(),
  }),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_header_retrieve: vi.fn().mockResolvedValue({
      job_id: 'job-1',
      job_number: 101,
      name: 'Rate Job',
      company_id: null,
      company_name: null,
      status: 'in_progress',
      pricing_methodology: 'time_materials',
      speed_quality_tradeoff: 'normal',
      fully_invoiced: false,
      quoted: false,
      quote_acceptance_date: null,
      paid: false,
      price_cap: null,
      default_xero_pay_item_id: null,
      default_xero_pay_item_name: null,
      rdti_type: null,
      is_urgent: false,
    }),
    workflow_xero_pay_items_list: vi.fn().mockResolvedValue([]),
    companies_jobs_person_retrieve: vi.fn().mockResolvedValue({ id: null, name: null }),
  },
}))

vi.mock('@/services/job.service', () => ({
  jobService: {
    getStatusChoices: vi.fn().mockResolvedValue({ statuses: { in_progress: 'In Progress' } }),
    getJobLabourRates: getJobLabourRatesMock,
    updateJobLabourRates: updateJobLabourRatesMock,
    updateJobHeaderPartial: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    beforeEach: vi.fn(() => vi.fn()),
  }),
}))

vi.mock('@/composables/useSaveFeedback', () => ({
  useSaveFeedback: () => ({
    pending: vi.fn(),
    saving: vi.fn(),
    saved: vi.fn(),
    error: vi.fn(),
    clear: vi.fn(),
  }),
}))

vi.mock('@/composables/useConcurrencyEvents', () => ({
  onConcurrencyRetry: vi.fn(() => vi.fn()),
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: toastErrorMock,
    success: vi.fn(),
  },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

vi.mock('@/api/generated/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/generated/api')>()
  return actual
})

import JobSettingsTab from '../JobSettingsTab.vue'

const passthrough = defineComponent({
  name: 'PassthroughStub',
  setup(_, { slots }) {
    return () => h('div', slots.default?.())
  },
})

const WORKSHOP_RATE = {
  id: 'rate-1',
  labour_subtype: 'subtype-1',
  labour_subtype_name: 'Workshop',
  is_workshop: true,
  charge_out_rate: 95,
}

const mountTab = () =>
  mount(JobSettingsTab, {
    props: {
      jobId: 'job-1',
      jobNumber: '101',
      pricingMethodology: 'time_materials',
      quoted: false,
      fullyInvoiced: false,
    },
    global: {
      stubs: {
        Card: passthrough,
        CardHeader: passthrough,
        CardTitle: passthrough,
        CardDescription: passthrough,
        CardContent: passthrough,
        RichTextEditor: { template: '<div />' },
        CompanyLookup: { template: '<div />' },
        PersonSelector: { template: '<div />' },
        CreateCompanyModal: { template: '<div />' },
      },
    },
  })

const rateInput = (wrapper: ReturnType<typeof mountTab>) =>
  wrapper.get('[data-automation-id="JobSettingsTab-labour-rate-Workshop"]')

describe('JobSettingsTab labour rate edit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getJobLabourRatesMock.mockResolvedValue([{ ...WORKSHOP_RATE }])
  })

  it('renders the persisted charge-out rate', async () => {
    const wrapper = mountTab()
    await flushPromises()

    expect((rateInput(wrapper).element as HTMLInputElement).value).toBe('95')
  })

  it('saves a valid edited rate and reflects the server response', async () => {
    updateJobLabourRatesMock.mockResolvedValue([{ ...WORKSHOP_RATE, charge_out_rate: 120 }])
    const wrapper = mountTab()
    await flushPromises()

    const input = rateInput(wrapper)
    await input.setValue('120')
    await input.trigger('blur')
    await flushPromises()

    expect(updateJobLabourRatesMock).toHaveBeenCalledWith('job-1', [
      { labour_subtype: 'subtype-1', charge_out_rate: 120 },
    ])
    expect((input.element as HTMLInputElement).value).toBe('120')
  })

  it('rejects a negative rate without calling the API and resets to the persisted value', async () => {
    const wrapper = mountTab()
    await flushPromises()

    const input = rateInput(wrapper)
    await input.setValue('-5')
    await input.trigger('blur')
    await flushPromises()

    expect(updateJobLabourRatesMock).not.toHaveBeenCalled()
    expect(toastErrorMock).toHaveBeenCalledWith('Charge-out rate must be a non-negative number')
    expect((input.element as HTMLInputElement).value).toBe('95')
  })

  it('rejects an empty rate (Number("")===0) without persisting a zero', async () => {
    const wrapper = mountTab()
    await flushPromises()

    const input = rateInput(wrapper)
    await input.setValue('')
    await input.trigger('blur')
    await flushPromises()

    expect(updateJobLabourRatesMock).not.toHaveBeenCalled()
    expect(toastErrorMock).toHaveBeenCalledWith('Charge-out rate must be a non-negative number')
    expect((input.element as HTMLInputElement).value).toBe('95')
  })

  it('rolls back to the persisted value when the save fails', async () => {
    updateJobLabourRatesMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountTab()
    await flushPromises()

    const input = rateInput(wrapper)
    await input.setValue('150')
    await input.trigger('blur')
    await flushPromises()

    expect(updateJobLabourRatesMock).toHaveBeenCalledTimes(1)
    expect((input.element as HTMLInputElement).value).toBe('95')
  })
})
