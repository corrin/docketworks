import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  api: {
    check_duplicate_identities: vi.fn(),
  },
}))

vi.mock('@/components/AppLayout.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))

vi.mock('vue-sonner', () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

import { api } from '@/api/client'
import DuplicateIdentitiesPage from '@/pages/reports/data-quality/duplicate-identities.vue'

const REVIEW_PERSON_GROUP = {
  group_id: 'person-review-1',
  fingerprint: 'fingerprint-1',
  recommendation: 'review' as const,
  reason_codes: ['cross_company_contact_conflict'],
  canonical_id: null,
  members: [
    {
      person_id: '11111111-1111-4111-8111-111111111111',
      name: 'Alex Smith',
      email: 'alex@example.com',
      is_active: true,
      created_at: '2026-07-13T00:00:00Z',
      updated_at: '2026-07-13T00:00:00Z',
      company_links: [
        {
          link_id: '22222222-2222-4222-8222-222222222222',
          company_id: '33333333-3333-4333-8333-333333333333',
          company_name: 'Alpha Limited',
          position: null,
          is_primary: true,
          is_active: true,
        },
      ],
      contact_methods: [],
      job_count: 1,
      phone_call_count: 2,
    },
    {
      person_id: '44444444-4444-4444-8444-444444444444',
      name: 'Alex Smith',
      email: 'alex@example.com',
      is_active: true,
      created_at: '2026-07-13T00:00:00Z',
      updated_at: '2026-07-13T00:00:00Z',
      company_links: [
        {
          link_id: '55555555-5555-4555-8555-555555555555',
          company_id: '66666666-6666-4666-8666-666666666666',
          company_name: 'Beta Limited',
          position: null,
          is_primary: true,
          is_active: true,
        },
      ],
      contact_methods: [],
      job_count: 0,
      phone_call_count: 0,
    },
  ],
  evidence: [{ kind: 'email' as const, normalized_value: 'alex@example.com', owner_count: 2 }],
}

const EMPTY_RESPONSE = {
  company_groups: [],
  person_groups: [],
  summary: {
    company_merge_groups: 0,
    company_review_groups: 0,
    person_merge_groups: 0,
    person_review_groups: 0,
  },
  checked_at: '2026-07-13T01:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('duplicate identities report', () => {
  it('emphasizes grouped exceptions after automatic cleanup is clear', async () => {
    vi.mocked(api.check_duplicate_identities).mockResolvedValue({
      ...EMPTY_RESPONSE,
      person_groups: [REVIEW_PERSON_GROUP],
      summary: { ...EMPTY_RESPONSE.summary, person_review_groups: 1 },
    })

    const wrapper = mount(DuplicateIdentitiesPage)
    await flushPromises()

    expect(api.check_duplicate_identities).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-automation-id="duplicate-identities-auto-clear"]').exists()).toBe(
      true,
    )
    expect(wrapper.text()).toContain('Needs review')
    expect(wrapper.text()).toContain('Alex Smith')
    expect(wrapper.text()).toContain('Alpha Limited')
    expect(wrapper.findAll('details')).toHaveLength(1)
  })

  it('warns when an automatic group remains', async () => {
    vi.mocked(api.check_duplicate_identities).mockResolvedValue({
      ...EMPTY_RESPONSE,
      company_groups: [
        {
          group_id: 'company-merge-1',
          fingerprint: 'fingerprint-2',
          recommendation: 'merge',
          reason_codes: ['exact_name'],
          canonical_id: '77777777-7777-4777-8777-777777777777',
          members: [
            {
              company_id: '77777777-7777-4777-8777-777777777777',
              name: 'Acme Limited',
              email: 'office@acme.example',
              address: '1 Test Street',
              allow_jobs: true,
              is_account_customer: true,
              is_supplier: false,
              xero_archived: false,
              job_count: 2,
              contact_names: [],
            },
            {
              company_id: '88888888-8888-4888-8888-888888888888',
              name: 'Acme Ltd',
              email: 'office@acme.example',
              address: '1 Test Street',
              allow_jobs: true,
              is_account_customer: true,
              is_supplier: false,
              xero_archived: false,
              job_count: 0,
              contact_names: [],
            },
          ],
          evidence: [{ kind: 'email', normalized_value: 'office@acme.example', owner_count: 2 }],
        },
      ],
      summary: { ...EMPTY_RESPONSE.summary, company_merge_groups: 1 },
    })

    const wrapper = mount(DuplicateIdentitiesPage)
    await flushPromises()

    expect(wrapper.find('[data-automation-id="duplicate-identities-auto-warning"]').exists()).toBe(
      true,
    )
    expect(wrapper.text()).toContain('1 automatic group remains')
    expect(wrapper.text()).toContain('Automatic matches')
    expect(wrapper.text()).toContain('Canonical')
  })

  it('shows the fully clear state when no grouped matches remain', async () => {
    vi.mocked(api.check_duplicate_identities).mockResolvedValue(EMPTY_RESPONSE)

    const wrapper = mount(DuplicateIdentitiesPage)
    await flushPromises()

    expect(wrapper.find('[data-automation-id="duplicate-identities-all-clear"]').exists()).toBe(
      true,
    )
    expect(wrapper.text()).toContain('No duplicate company or person groups remain')
  })

  it('clears stale groups when refreshing fails', async () => {
    vi.mocked(api.check_duplicate_identities).mockResolvedValueOnce({
      ...EMPTY_RESPONSE,
      person_groups: [REVIEW_PERSON_GROUP],
      summary: { ...EMPTY_RESPONSE.summary, person_review_groups: 1 },
    })

    const wrapper = mount(DuplicateIdentitiesPage)
    await flushPromises()
    expect(wrapper.findAll('details')).toHaveLength(1)

    vi.mocked(api.check_duplicate_identities).mockRejectedValueOnce(new Error('Report failed'))
    await wrapper.find('[data-automation-id="duplicate-identities-refresh"]').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('details')).toHaveLength(0)
    expect(wrapper.find('[data-automation-id="duplicate-identities-error"]').text()).toContain(
      'Report failed',
    )
  })
})
