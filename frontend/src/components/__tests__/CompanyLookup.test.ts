import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

vi.mock('@/composables/useCompanyLookup', () => ({
  useCompanyLookup: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: { companies_create_create: vi.fn() },
}))

vi.mock('@/components/CreateCompanyModal.vue', () => ({
  default: { template: '<div />' },
}))

import CompanyLookup from '../CompanyLookup.vue'
import { useCompanyLookup, type Company } from '@/composables/useCompanyLookup'

function buildComposableStub(suggestions: Company[]) {
  return {
    searchQuery: ref('msm'),
    suggestions: ref(suggestions),
    isLoading: ref(false),
    showSuggestions: ref(true),
    selectedCompany: ref(null),
    contacts: ref([]),
    hasValidXeroId: ref(false),
    displayValue: ref(''),
    searchCompanies: vi.fn(),
    selectCompany: vi.fn(),
    loadClientContacts: vi.fn(),
    getPrimaryContact: vi.fn(),
    clearSelection: vi.fn(),
    handleInputChange: vi.fn(),
    createNewCompany: vi.fn(),
    hideSuggestions: vi.fn(),
    resetToInitialState: vi.fn(),
    preserveSelectedCompany: vi.fn(),
  } as unknown as ReturnType<typeof useCompanyLookup>
}

const sampleCompany: Company = {
  id: 'c1',
  name: 'MSM (Shop)',
  email: 'lakeland@gmail.com',
  phone: '',
  address: '',
  is_account_customer: false,
  is_supplier: false,
  allow_jobs: true,
  xero_contact_id: 'xero-1',
  last_invoice_date: null,
  total_spend: '0',
}

describe('CompanyLookup option rendering', () => {
  beforeEach(() => {
    vi.mocked(useCompanyLookup).mockReturnValue(buildComposableStub([sampleCompany]))
  })

  it('renders the company name as the only text inside role="option"', () => {
    const wrapper = mount(CompanyLookup, {
      props: { id: 'lookup', label: 'Company' },
    })

    const option = wrapper.find('[role="option"]')
    expect(option.exists()).toBe(true)
    expect(option.text()).toBe('MSM (Shop)')
    expect(option.text()).not.toContain('lakeland@gmail.com')
  })
})
