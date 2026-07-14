import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PersonSelectionModal from '@/components/PersonSelectionModal.vue'

const companyId = '11111111-1111-4111-8111-111111111111'
const form = {
  name: 'Jane Duplicate',
  email: 'jane@example.com',
  phone: '021 555 0100',
  position: '',
  notes: '',
  is_primary: false,
}
const dialogStubs = {
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
}

describe('PersonSelectionModal phone ownership choices', () => {
  it('renders every candidate with link, restore, or select wording', () => {
    const wrapper = mount(PersonSelectionModal, {
      props: {
        isOpen: true,
        companyId,
        companyName: 'Current Company',
        people: [],
        selectedPerson: null,
        isLoading: false,
        personForm: form,
        phoneOwnership: {
          status: 'people',
          normalized_phone: '+64215550100',
          can_create_person: true,
          companies: [],
          people: [
            {
              person_id: '22222222-2222-4222-8222-222222222222',
              person_name: 'Already Linked',
              person_email: null,
              company_links: [
                {
                  company_id: companyId,
                  company_name: 'Current Company',
                  position: null,
                  notes: null,
                  is_primary: true,
                  is_active: true,
                },
              ],
            },
            {
              person_id: '33333333-3333-4333-8333-333333333333',
              person_name: 'Inactive Link',
              person_email: null,
              company_links: [
                {
                  company_id: companyId,
                  company_name: 'Current Company',
                  position: null,
                  notes: null,
                  is_primary: false,
                  is_active: false,
                },
              ],
            },
            {
              person_id: '44444444-4444-4444-8444-444444444444',
              person_name: 'Other Company',
              person_email: null,
              company_links: [],
            },
          ],
        },
      },
      global: { stubs: dialogStubs },
    })

    expect(wrapper.text()).toContain('Select person')
    expect(wrapper.text()).toContain('Restore company link')
    expect(wrapper.text()).toContain('Link to this company')
    expect(
      wrapper.find('[data-automation-id="PersonSelectionModal-create-separate"]').exists(),
    ).toBe(true)
  })

  it('renders a hard company-owner conflict without reuse actions', () => {
    const wrapper = mount(PersonSelectionModal, {
      props: {
        isOpen: true,
        companyId,
        companyName: 'Current Company',
        people: [],
        selectedPerson: null,
        isLoading: false,
        personForm: form,
        phoneOwnership: {
          status: 'company',
          normalized_phone: '+6495550100',
          can_create_person: false,
          people: [],
          companies: [
            {
              company_id: '55555555-5555-4555-8555-555555555555',
              company_name: 'Owner Company',
            },
          ],
        },
      },
      global: { stubs: dialogStubs },
    })

    expect(wrapper.text()).toContain('Owner Company')
    expect(wrapper.find('[data-automation-id^="PersonSelectionModal-link-match-"]').exists()).toBe(
      false,
    )
    expect(
      wrapper.find('[data-automation-id="PersonSelectionModal-create-separate"]').exists(),
    ).toBe(false)
  })
})
