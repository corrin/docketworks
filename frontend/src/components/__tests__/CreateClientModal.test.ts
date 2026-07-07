import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('@/api/client', () => ({
  api: { clients_update_update: vi.fn(), clients_create_create: vi.fn() },
}))

import CreateClientModal from '../CreateClientModal.vue'
import { api } from '@/api/client'

// The modal's Dialog primitives (reka-ui) render via Teleport, which is
// irrelevant to the phone-field behaviour under test; stub them to plain
// pass-through markup so the form is queryable directly.
const stubs = {
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
  Button: { template: '<button><slot /></button>' },
}

const editClientData = {
  name: 'Acme Ltd',
  email: 'acme@example.com',
  phone: '09 111 1111',
  address: '1 Foo St',
  is_account_customer: true,
  allow_jobs: true,
}

describe('CreateClientModal edit-mode phone (restored after the ClientContactMethod migration dropped it)', () => {
  it('shows the phone input in edit mode, pre-populated from clientData', async () => {
    const wrapper = mount(CreateClientModal, {
      props: {
        isOpen: false,
        editMode: true,
        clientId: 'client-1',
        clientData: editClientData,
      },
      global: { stubs },
    })
    // Pre-population runs on the isOpen watcher, matching how the parent
    // opens the modal (false -> true), not on initial mount.
    await wrapper.setProps({ isOpen: true })

    const phoneInput = wrapper.find('#clientPhone')
    expect(phoneInput.exists()).toBe(true)
    expect((phoneInput.element as HTMLInputElement).value).toBe('09 111 1111')
  })

  it('includes the edited phone in the update payload on submit', async () => {
    vi.mocked(api.clients_update_update).mockResolvedValue({
      success: true,
      message: 'Client updated',
      client: {
        id: 'client-1',
        name: 'Acme Ltd',
        email: 'acme@example.com',
        phone: '09 222 2222',
        address: '1 Foo St',
        is_account_customer: true,
        is_supplier: false,
        allow_jobs: true,
        xero_contact_id: 'xero-1',
        last_invoice_date: null,
        total_spend: '0',
      },
    } as never)

    const wrapper = mount(CreateClientModal, {
      props: {
        isOpen: false,
        editMode: true,
        clientId: 'client-1',
        clientData: editClientData,
      },
      global: { stubs },
    })
    // Pre-population runs on the isOpen watcher, matching how the parent
    // opens the modal (false -> true), not on initial mount.
    await wrapper.setProps({ isOpen: true })

    await wrapper.find('#clientPhone').setValue('09 222 2222')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.clients_update_update).toHaveBeenCalledWith(
      expect.objectContaining({ phone: '09 222 2222' }),
      { params: { client_id: 'client-1' } },
    )
  })
})
