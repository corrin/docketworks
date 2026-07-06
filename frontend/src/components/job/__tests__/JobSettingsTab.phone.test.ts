import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

const { headerRetrieveMock, contactRetrieveMock } = vi.hoisted(() => ({
  headerRetrieveMock: vi.fn(),
  contactRetrieveMock: vi.fn(),
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
  }),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_header_retrieve: headerRetrieveMock,
    workflow_xero_pay_items_list: vi.fn().mockResolvedValue([]),
    clients_jobs_contact_retrieve: contactRetrieveMock,
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

const BASE_HEADER = {
  job_id: 'job-1',
  job_number: 101,
  name: 'Phone Job',
  client_id: 'client-1',
  client_name: 'Acme Ltd',
  client_phone: '',
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
}

const CONTACT_WITHOUT_PHONE = {
  id: 'contact-1',
  name: 'Jane Doe',
  email: null,
  position: null,
  is_primary: true,
  notes: null,
  phone: '',
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
        ClientLookup: { template: '<div />' },
        ContactSelector: { template: '<div />' },
        CreateClientModal: { template: '<div />' },
      },
    },
  })

describe('JobSettingsTab phone display (KAN-281)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    headerRetrieveMock.mockResolvedValue({ ...BASE_HEADER })
    contactRetrieveMock.mockResolvedValue({ ...CONTACT_WITHOUT_PHONE })
  })

  it('renders the contact phone read-only when the contact has a phone', async () => {
    contactRetrieveMock.mockResolvedValue({
      ...CONTACT_WITHOUT_PHONE,
      phone: '+64 21 555 0100',
    })

    const wrapper = mountTab()
    await flushPromises()

    const input = wrapper.get('[data-automation-id="JobSettingsTab-contact-phone"]')
    expect((input.element as HTMLInputElement).value).toBe('+64 21 555 0100')
    expect(input.attributes('readonly')).toBeDefined()
  })

  it('renders no phone fields when neither contact nor client has a phone', async () => {
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.find('[data-automation-id="JobSettingsTab-contact-phone"]').exists()).toBe(false)
    expect(wrapper.find('[data-automation-id="JobSettingsTab-client-phone"]').exists()).toBe(false)
  })

  it('renders the client phone read-only when the job header payload has one', async () => {
    headerRetrieveMock.mockResolvedValue({ ...BASE_HEADER, client_phone: '09 555 1234' })
    contactRetrieveMock.mockRejectedValue({ response: { status: 404 } })

    const wrapper = mountTab()
    await flushPromises()

    const input = wrapper.get('[data-automation-id="JobSettingsTab-client-phone"]')
    expect((input.element as HTMLInputElement).value).toBe('09 555 1234')
    expect(input.attributes('readonly')).toBeDefined()
    // No contact phone artifact when the job has no contact
    expect(wrapper.find('[data-automation-id="JobSettingsTab-contact-phone"]').exists()).toBe(false)
  })
})
