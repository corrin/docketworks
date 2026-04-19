import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

vi.mock('@/composables/useClientLookup', () => ({
  useClientLookup: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: { clients_create_create: vi.fn() },
}))

vi.mock('@/components/CreateClientModal.vue', () => ({
  default: { template: '<div />' },
}))

import ClientLookup from '../ClientLookup.vue'
import { useClientLookup, type Client } from '@/composables/useClientLookup'

function buildComposableStub(suggestions: Client[]) {
  return {
    searchQuery: ref('msm'),
    suggestions: ref(suggestions),
    isLoading: ref(false),
    showSuggestions: ref(true),
    selectedClient: ref(null),
    contacts: ref([]),
    hasValidXeroId: ref(false),
    displayValue: ref(''),
    searchClients: vi.fn(),
    selectClient: vi.fn(),
    loadClientContacts: vi.fn(),
    getPrimaryContact: vi.fn(),
    clearSelection: vi.fn(),
    handleInputChange: vi.fn(),
    createNewClient: vi.fn(),
    hideSuggestions: vi.fn(),
    resetToInitialState: vi.fn(),
    preserveSelectedClient: vi.fn(),
  } as unknown as ReturnType<typeof useClientLookup>
}

const sampleClient: Client = {
  id: 'c1',
  name: 'MSM (Shop)',
  email: 'lakeland@gmail.com',
  phone: '',
  address: '',
  is_account_customer: false,
  is_supplier: false,
  xero_contact_id: 'xero-1',
  last_invoice_date: null,
  total_spend: '0',
}

describe('ClientLookup option rendering', () => {
  beforeEach(() => {
    vi.mocked(useClientLookup).mockReturnValue(buildComposableStub([sampleClient]))
  })

  it('renders the client name as the only text inside role="option"', () => {
    const wrapper = mount(ClientLookup, {
      props: { id: 'lookup', label: 'Client' },
    })

    const option = wrapper.find('[role="option"]')
    expect(option.exists()).toBe(true)
    expect(option.text()).toBe('MSM (Shop)')
    expect(option.text()).not.toContain('lakeland@gmail.com')
  })
})
