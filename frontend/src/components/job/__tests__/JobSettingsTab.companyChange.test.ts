import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

const { capturedConfig, updateJobHeaderPartial } = vi.hoisted(() => ({
  capturedConfig: {
    value: null as { saveAdapter: (patch: Record<string, unknown>) => unknown } | null,
  },
  updateJobHeaderPartial: vi.fn(),
}))

vi.mock('@/composables/useJobAutosave', () => ({
  createJobAutosave: (config: { saveAdapter: (patch: Record<string, unknown>) => unknown }) => {
    capturedConfig.value = config
    return {
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
    }
  },
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
      name: 'Job',
      company_id: 'company-1',
      company_name: 'Company One',
      person_id: 'person-1',
      person_name: 'Alice',
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
    getJobLabourRates: vi.fn().mockResolvedValue([]),
    updateJobHeaderPartial,
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ beforeEach: vi.fn(() => vi.fn()) }),
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
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('@/utils/debug', () => ({
  debugLog: vi.fn(),
}))

import JobSettingsTab from '../JobSettingsTab.vue'

const passthrough = defineComponent({
  name: 'PassthroughStub',
  setup(_, { slots }) {
    return () => h('div', slots.default?.())
  },
})

describe('JobSettingsTab company-change autosave', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    updateJobHeaderPartial.mockResolvedValue({
      success: true,
      data: {
        data: {
          job: {
            id: 'job-1',
            company_id: 'company-2',
            company_name: 'Company Two',
            person_id: null,
            person_name: null,
          },
        },
      },
    })
  })

  it('never sends person_name on the wire when the company changes', async () => {
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
    await flushPromises()

    expect(capturedConfig.value).not.toBeNull()

    await capturedConfig.value!.saveAdapter({
      company_id: 'company-2',
      company_name: 'Company Two',
      person_id: null,
      person_name: null,
    })

    expect(updateJobHeaderPartial).toHaveBeenCalledTimes(1)
    const payload = updateJobHeaderPartial.mock.calls[0][1] as Record<string, unknown>
    expect(payload).toMatchObject({ company_id: 'company-2', person_id: null })
    expect(Object.keys(payload)).not.toContain('person_name')
  })
})
