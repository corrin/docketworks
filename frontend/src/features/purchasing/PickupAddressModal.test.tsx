import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { SupplierPickupAddressOut } from '@/api'
import { autoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { PickupAddressModal } from './PickupAddressModal'

const LIST = '*/api/companies/pickup-addresses/'
const ONE = '*/api/companies/pickup-addresses/:id/'
const SUPPLIER = { id: 'supplier-1', name: 'Metal Supplies Ltd' }

function address(overrides: Partial<SupplierPickupAddressOut> = {}): SupplierPickupAddressOut {
  return {
    id: 'addr-1',
    company: SUPPLIER.id,
    name: 'Main yard',
    street: '1 Steel Road',
    suburb: 'Penrose',
    city: 'Auckland',
    state: null,
    postal_code: '1061',
    country: 'New Zealand',
    google_place_id: null,
    latitude: null,
    longitude: null,
    is_primary: true,
    notes: null,
    is_active: true,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    formatted_address: '1 Steel Road, Penrose, Auckland, 1061',
    ...overrides,
  }
}

function mockList(addresses: SupplierPickupAddressOut[]): string[] {
  const supplierIds: string[] = []
  server.use(
    http.get(LIST, ({ request }) => {
      supplierIds.push(new URL(request.url).searchParams.get('supplier_id') ?? '')
      return HttpResponse.json(addresses)
    }),
  )
  return supplierIds
}

async function renderModal(props: Partial<React.ComponentProps<typeof PickupAddressModal>> = {}) {
  const onSelect = vi.fn()
  const onClose = vi.fn()
  const result = renderWithProviders(
    <PickupAddressModal
      open
      supplier={SUPPLIER}
      selectedId={null}
      onClose={onClose}
      onSelect={onSelect}
      {...props}
    />,
  )
  await screen.findByText(`Pickup address for ${SUPPLIER.name}`)
  return { ...result, onSelect, onClose }
}

describe('PickupAddressModal', () => {
  it("lists the supplier's addresses and Select hands one back", async () => {
    const supplierIds = mockList([address()])
    const { user, onSelect } = await renderModal()

    await screen.findByText('Main yard')
    expect(supplierIds).toEqual([SUPPLIER.id])
    await user.click(autoId('PickupAddressSelectionModal-select-button'))

    expect(onSelect).toHaveBeenCalledWith(address())
  })

  it('creating an address posts the form for this supplier and selects the result', async () => {
    mockList([])
    const bodies: unknown[] = []
    const created = address({ id: 'addr-new', name: 'Hillsborough site', is_primary: true })
    server.use(
      http.post(LIST, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const { user, onSelect, onClose } = await renderModal()
    await screen.findByText(/No pickup addresses yet/)

    await user.type(autoId('PickupAddressSelectionModal-name-input'), 'Hillsborough site')
    await user.type(autoId('AddressAutocompleteInput'), '7C Aldersgate Road')
    await user.type(screen.getByPlaceholderText('City'), 'Auckland')
    await user.click(autoId('PickupAddressSelectionModal-submit'))

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({
      company: SUPPLIER.id,
      name: 'Hillsborough site',
      street: '7C Aldersgate Road',
      suburb: null,
      city: 'Auckland',
      state: null,
      postal_code: null,
      notes: null,
      // The supplier's first address is its primary, so PO creation can find it.
      is_primary: true,
      google_place_id: null,
      latitude: null,
      longitude: null,
    })
    expect(onSelect).toHaveBeenCalledWith(created)
    expect(onClose).toHaveBeenCalled()
  })

  it('editing patches only that address', async () => {
    mockList([address()])
    const patches: { id: string; body: unknown }[] = []
    server.use(
      http.patch(ONE, async ({ request, params }) => {
        patches.push({ id: String(params.id), body: await request.json() })
        return HttpResponse.json(address({ name: 'Back gate' }))
      }),
    )
    const { user } = await renderModal()
    await screen.findByText('Main yard')

    await user.click(screen.getByRole('button', { name: 'Edit Main yard' }))
    const name = autoId('PickupAddressSelectionModal-name-input')
    expect(name).toHaveValue('Main yard')
    await user.clear(name)
    await user.type(name, 'Back gate')
    await user.click(autoId('PickupAddressSelectionModal-submit'))

    await waitFor(() => expect(patches).toHaveLength(1))
    expect(patches).toEqual([
      {
        id: 'addr-1',
        body: expect.objectContaining({ name: 'Back gate', street: '1 Steel Road' }),
      },
    ])
  })

  it('deleting asks first, then sends the DELETE', async () => {
    mockList([address()])
    const deleted: string[] = []
    server.use(
      http.delete(ONE, ({ params }) => {
        deleted.push(String(params.id))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = await renderModal()
    await screen.findByText('Main yard')

    await user.click(screen.getByRole('button', { name: 'Delete Main yard' }))
    expect(deleted).toEqual([])
    const prompt = screen.getByText('Delete Address?').closest('div')
    if (!prompt) throw new Error('no confirmation')
    await user.click(within(prompt).getByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(deleted).toEqual(['addr-1']))
  })
})
