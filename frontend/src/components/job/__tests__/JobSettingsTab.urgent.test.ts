import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

const { queueChangeMock } = vi.hoisted(() => ({
  queueChangeMock: vi.fn(),
}))

vi.mock('@/composables/useJobAutosave', () => ({
  createJobAutosave: () => ({
    queueChange: queueChangeMock,
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
  }),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_header_retrieve: vi.fn().mockResolvedValue({
      job_id: 'job-1',
      job_number: 101,
      name: 'Urgent Job',
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
      is_urgent: true,
    }),
    workflow_xero_pay_items_list: vi.fn().mockResolvedValue([]),
    companies_jobs_contact_retrieve: vi.fn().mockResolvedValue({ id: null, name: null }),
  },
}))

vi.mock('@/services/job.service', () => ({
  jobService: {
    getStatusChoices: vi.fn().mockResolvedValue({ statuses: { in_progress: 'In Progress' } }),
    getJobLabourRates: vi.fn().mockResolvedValue([]),
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
    error: vi.fn(),
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

describe('JobSettingsTab urgent autosave', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('queues urgent=false as a boolean instead of the truthy string "false"', async () => {
    const wrapper = mount(JobSettingsTab, {
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
          ContactSelector: { template: '<div />' },
          CreateCompanyModal: { template: '<div />' },
        },
      },
    })
    await flushPromises()

    queueChangeMock.mockClear()
    await wrapper.get('[data-automation-id="JobSettingsTab-is-urgent"]').setValue('false')

    expect(queueChangeMock).toHaveBeenCalledWith('is_urgent', false)
  })
})
