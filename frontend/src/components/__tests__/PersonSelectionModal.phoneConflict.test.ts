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
        editingPerson: null,
        isEditing: false,
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
        editingPerson: null,
        isEditing: false,
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

const person = {
  person_id: '66666666-6666-4666-8666-666666666666',
  person_name: 'Edit Target',
  person_email: 'edit@example.com',
  primary_phone: '021 555 0199',
  position: 'Manager',
  is_primary: true,
  notes: '',
}

const mountWithPerson = () =>
  mount(PersonSelectionModal, {
    props: {
      isOpen: true,
      companyId,
      companyName: 'Current Company',
      people: [person],
      selectedPerson: null,
      isLoading: false,
      personForm: form,
      phoneOwnership: null,
      editingPerson: null,
      isEditing: false,
    },
    global: { stubs: dialogStubs },
  })

describe('PersonSelectionModal edit and delete actions', () => {
  it('emits edit-person when the edit button is clicked', async () => {
    const wrapper = mountWithPerson()

    await wrapper.find('[data-automation-id="PersonSelectionModal-edit-button"]').trigger('click')

    const edits = wrapper.emitted('edit-person')
    expect(edits).toBeTruthy()
    expect((edits![0][0] as { person_id: string }).person_id).toBe(person.person_id)
  })

  it('opens the confirm overlay and emits delete-person on confirm', async () => {
    const wrapper = mountWithPerson()

    expect(
      wrapper.find('[data-automation-id="PersonSelectionModal-confirm-delete"]').exists(),
    ).toBe(false)

    await wrapper.find('[data-automation-id="PersonSelectionModal-delete-button"]').trigger('click')

    expect(wrapper.text()).toContain('Delete Person?')
    expect(
      wrapper.find('[data-automation-id="PersonSelectionModal-confirm-delete"]').exists(),
    ).toBe(true)

    await wrapper
      .find('[data-automation-id="PersonSelectionModal-confirm-delete"]')
      .trigger('click')

    const deletes = wrapper.emitted('delete-person')
    expect(deletes).toBeTruthy()
    expect((deletes![0][0] as { person_id: string }).person_id).toBe(person.person_id)
  })

  it('shows the primary warning in the confirm overlay for a primary person', async () => {
    const wrapper = mountWithPerson()

    await wrapper.find('[data-automation-id="PersonSelectionModal-delete-button"]').trigger('click')

    expect(wrapper.text()).toContain('This is the primary person for this company.')
  })

  it('closes the confirm overlay without emitting on cancel', async () => {
    const wrapper = mountWithPerson()

    await wrapper.find('[data-automation-id="PersonSelectionModal-delete-button"]').trigger('click')
    await wrapper.find('[data-automation-id="PersonSelectionModal-cancel-delete"]').trigger('click')

    expect(
      wrapper.find('[data-automation-id="PersonSelectionModal-confirm-delete"]').exists(),
    ).toBe(false)
    expect(wrapper.emitted('delete-person')).toBeFalsy()
  })
})
