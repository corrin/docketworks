import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AdminLabourSubtypesView from '../AdminLabourSubtypesView.vue'

const { listLabourSubtypesMock, updateLabourSubtypeMock, apiError } = vi.hoisted(() => ({
  listLabourSubtypesMock: vi.fn(),
  updateLabourSubtypeMock: vi.fn(),
  apiError: { value: null as string | null, __v_isRef: true },
}))

vi.mock('@/composables/useLabourSubtypesApi', () => ({
  useLabourSubtypesApi: () => ({
    listLabourSubtypes: listLabourSubtypesMock,
    updateLabourSubtype: updateLabourSubtypeMock,
    error: apiError,
  }),
}))

vi.mock('@/api/generated/api', () => ({
  schemas: {
    LabourSubtypeManage: {},
  },
  endpoints: [],
}))

vi.mock('@/api/client', () => ({
  api: {},
  getApi: () => ({}),
}))

vi.mock('@/components/AppLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

function mountView() {
  return mount(AdminLabourSubtypesView, {
    global: {
      stubs: {
        AppLayout: { template: '<div><slot /></div>' },
        Button: { template: '<button><slot /></button>' },
        LabourSubtypeFormModal: { template: '<div />' },
        ConfirmModal: { template: '<div />' },
        Wrench: { template: '<span />' },
        PencilLine: { template: '<span />' },
        Ban: { template: '<span />' },
      },
    },
  })
}

describe('AdminLabourSubtypesView loading states', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiError.value = null
  })

  it('shows an API error instead of the empty state when subtype loading fails', async () => {
    apiError.value = 'Failed to load labour subtypes.'
    listLabourSubtypesMock.mockRejectedValue(new Error('Failed to load labour subtypes.'))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Failed to load labour subtypes.')
    expect(wrapper.text()).not.toContain('No labour subtypes found.')
  })

  it('keeps the empty state for a successful empty subtype list', async () => {
    listLabourSubtypesMock.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('No labour subtypes found.')
  })
})
