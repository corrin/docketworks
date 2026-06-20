import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import type { JobErrorFilterState, SystemErrorFilterState } from '@/types/errorFilters'

// The grouped job-error and grouped xero-error endpoints are the calls these
// tests exercise. Mock the generated client so we can assert the query params
// forwarded to them and feed canned grouped responses back through the view's
// mapping.
const { groupedRetrieveMock, xeroGroupedRetrieveMock } = vi.hoisted(() => ({
  groupedRetrieveMock: vi.fn(),
  xeroGroupedRetrieveMock: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  api: {
    job_jobs_delta_rejections_grouped_retrieve: groupedRetrieveMock,
    xero_errors_grouped_retrieve: xeroGroupedRetrieveMock,
    // Other tabs are never reached in these tests but the composable references
    // them; provide no-op stubs so property access doesn't throw.
    app_errors_grouped_retrieve: vi.fn(),
  },
}))

vi.mock('@/components/AppLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))

// Stub the tab switcher and filter so the test can drive the job tab and the
// resolved filter without depending on shadcn Select internals.
vi.mock('@/components/admin/errors/ErrorTabs.vue', () => ({
  default: defineComponent({
    name: 'ErrorTabs',
    props: { modelValue: { type: String, required: true } },
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('div', [
          h('button', {
            'data-test': 'tab-job',
            onClick: () => emit('update:modelValue', 'job'),
          }),
          h('button', {
            'data-test': 'tab-xero',
            onClick: () => emit('update:modelValue', 'xero'),
          }),
        ])
    },
  }),
}))

// The xero tab reuses SystemErrorFilter. Stub it with a resolved control so the
// test can drive Resolved=true without depending on shadcn Select internals.
vi.mock('@/components/admin/errors/SystemErrorFilter.vue', () => ({
  default: defineComponent({
    name: 'SystemErrorFilter',
    props: { modelValue: { type: Object, required: true } },
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('button', {
          'data-test': 'system-set-resolved-true',
          onClick: () =>
            emit('update:modelValue', {
              ...(props.modelValue as SystemErrorFilterState),
              resolved: 'true',
            }),
        })
    },
  }),
}))

vi.mock('@/components/admin/errors/JobErrorFilter.vue', () => ({
  default: defineComponent({
    name: 'JobErrorFilter',
    props: { modelValue: { type: Object, required: true } },
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('button', {
          'data-test': 'set-resolved-true',
          onClick: () =>
            emit('update:modelValue', {
              ...(props.modelValue as JobErrorFilterState),
              resolved: 'true',
            }),
        })
    },
  }),
}))

// Capture the rows handed to the table so we can read the mapped `resolved`.
const { capturedRows } = vi.hoisted(() => ({
  capturedRows: { value: [] as Array<{ resolved: boolean; fingerprint: string }> },
}))

vi.mock('@/components/admin/errors/ErrorTable.vue', () => ({
  default: defineComponent({
    name: 'ErrorTable',
    props: { rows: { type: Array, default: () => [] } },
    setup(props) {
      return () => {
        capturedRows.value = props.rows as Array<{ resolved: boolean; fingerprint: string }>
        return h('div', { 'data-test': 'error-table' })
      }
    },
  }),
}))

vi.mock('@/components/admin/errors/ErrorDialog.vue', () => ({
  default: { template: '<div />' },
}))

vi.mock('vue-sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

import AdminErrorView from '../AdminErrorView.vue'

function mountView() {
  return mount(AdminErrorView, {
    global: {
      stubs: {
        AppLayout: { template: '<div><slot /></div>' },
        Alert: { template: '<div><slot /></div>' },
        Progress: { template: '<div />' },
      },
    },
  })
}

describe('AdminErrorView job resolved filter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedRows.value = []
    xeroGroupedRetrieveMock.mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      results: [],
    })
    groupedRetrieveMock.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          fingerprint: 'fp-1',
          reason: 'Delta rejected',
          occurrence_count: 3,
          first_seen: '2026-06-01T00:00:00Z',
          last_seen: '2026-06-02T00:00:00Z',
          latest_id: '11111111-1111-1111-1111-111111111111',
          resolved: true,
        },
      ],
    })
  })

  it('forwards resolved:true to the grouped job endpoint and maps the response resolved flag', async () => {
    const wrapper = mountView()
    await flushPromises()

    // Switch to the job tab.
    await wrapper.get('[data-test="tab-job"]').trigger('click')
    await flushPromises()

    // Select Resolved = true via the (stubbed) job filter.
    await wrapper.get('[data-test="set-resolved-true"]').trigger('click')
    await flushPromises()

    // (a) The filter is forwarded as resolved:true on the query.
    const lastCall = groupedRetrieveMock.mock.calls.at(-1)
    expect(lastCall).toBeTruthy()
    expect(lastCall![0].queries.resolved).toBe(true)

    // (b) The grouped row's `resolved` is read from the API response, not
    // hardcoded — so a resolved group maps to resolved:true (Unresolve action).
    const row = capturedRows.value.find((r) => r.fingerprint === 'fp-1')
    expect(row).toBeTruthy()
    expect(row!.resolved).toBe(true)
  })
})

describe('AdminErrorView xero resolved filter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    capturedRows.value = []
    groupedRetrieveMock.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    xeroGroupedRetrieveMock.mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      results: [],
    })
  })

  it('renders the resolved filter control on the xero tab and forwards resolved:true to the grouped xero endpoint', async () => {
    const wrapper = mountView()
    await flushPromises()

    // The xero tab is the default; the System filter (with the resolved
    // control) renders for it.
    expect(wrapper.find('[data-test="system-set-resolved-true"]').exists()).toBe(true)

    // Select Resolved = true via the (stubbed) system filter.
    await wrapper.get('[data-test="system-set-resolved-true"]').trigger('click')
    await flushPromises()

    const lastCall = xeroGroupedRetrieveMock.mock.calls.at(-1)
    expect(lastCall).toBeTruthy()
    expect(lastCall![0].queries.resolved).toBe(true)
  })
})
