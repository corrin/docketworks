import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { SupplierPickupAddressOut } from '@/api'
import { expectNoAccessibilityViolations } from '@/test/accessibility'
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
    google_place_id: 'place-1',
    latitude: -36.9,
    longitude: 174.8,
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
    // The street field queries this as it is typed; no candidates here.
    http.post('*/api/companies/addresses/validate/', () => HttpResponse.json({ candidates: [] })),
  )
  return supplierIds
}

async function renderModal() {
  const onSelect = vi.fn()
  const onClose = vi.fn()
  const onUpdated = vi.fn()
  const onDeleted = vi.fn()
  const result = renderWithProviders(
    <PickupAddressModal
      open
      supplier={SUPPLIER}
      selectedId={null}
      onClose={onClose}
      onSelect={onSelect}
      onUpdated={onUpdated}
      onDeleted={onDeleted}
    />,
  )
  await screen.findByText(`Pickup address for ${SUPPLIER.name}`)
  return { ...result, onSelect, onClose, onUpdated, onDeleted }
}

describe('PickupAddressModal', () => {
  it("lists the supplier's addresses and Select hands one back", async () => {
    const supplierIds = mockList([address()])
    const { user, onSelect, baseElement } = await renderModal()

    await screen.findByText('Main yard')
    expect(supplierIds).toEqual([SUPPLIER.id])
    await expectNoAccessibilityViolations(baseElement)
    await user.click(autoId('PickupAddressSelectionModal-select-addr-1'))

    expect(onSelect).toHaveBeenCalledWith(address())
  })

  it('creating an address posts the form for this supplier and selects the result', async () => {
    mockList([])
    const bodies: unknown[] = []
    const created = address({ id: 'addr-new', name: 'Hillsborough site' })
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
    await user.type(autoId('PickupAddressSelectionModal-city-input'), 'Auckland')
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
      // Primary is the server's call for a first address; the box was untouched.
      is_primary: false,
      google_place_id: null,
      latitude: null,
      longitude: null,
    })
    expect(onSelect).toHaveBeenCalledWith(created)
    expect(onClose).toHaveBeenCalled()
  })

  it('editing sends the whole address back to its own id', async () => {
    mockList([address()])
    const puts: { id: string; body: unknown }[] = []
    server.use(
      http.put(ONE, async ({ request, params }) => {
        puts.push({ id: String(params.id), body: await request.json() })
        return HttpResponse.json(address({ name: 'Back gate' }))
      }),
    )
    const { user, onUpdated } = await renderModal()
    await screen.findByText('Main yard')

    await user.click(autoId('PickupAddressSelectionModal-edit-addr-1'))
    const name = autoId('PickupAddressSelectionModal-name-input')
    expect(name).toHaveValue('Main yard')
    await user.clear(name)
    await user.type(name, 'Back gate')
    await user.click(autoId('PickupAddressSelectionModal-submit'))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts).toEqual([
      {
        id: 'addr-1',
        body: expect.objectContaining({
          name: 'Back gate',
          street: '1 Steel Road',
          google_place_id: 'place-1',
        }),
      },
    ])
    // The owner hears about the edit, so a selected address is shown as saved.
    expect(onUpdated).toHaveBeenCalledWith(address({ name: 'Back gate' }))
  })

  it('retyping the street by hand drops the geocode that described the old one', async () => {
    mockList([address()])
    const puts: unknown[] = []
    server.use(
      http.put(ONE, async ({ request }) => {
        puts.push(await request.json())
        return HttpResponse.json(address())
      }),
    )
    const { user } = await renderModal()
    await screen.findByText('Main yard')

    await user.click(autoId('PickupAddressSelectionModal-edit-addr-1'))
    await user.type(autoId('AddressAutocompleteInput'), 'A')
    await user.click(autoId('PickupAddressSelectionModal-submit'))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]).toEqual(
      expect.objectContaining({
        street: '1 Steel RoadA',
        google_place_id: null,
        latitude: null,
        longitude: null,
      }),
    )
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
    const { user, onDeleted, baseElement } = await renderModal()
    await screen.findByText('Main yard')

    await user.click(autoId('PickupAddressSelectionModal-delete-addr-1'))
    expect(await screen.findByText('Delete Address?')).toBeInTheDocument()
    // The confirmation is a dialog of its own: focus lands in it, and the
    // list behind it is inert.
    expect(autoId('PickupAddressSelectionModal-confirm')).toContainElement(
      document.activeElement instanceof HTMLElement ? document.activeElement : null,
    )
    await expectNoAccessibilityViolations(baseElement)
    expect(deleted).toEqual([])
    await user.click(autoId('PickupAddressSelectionModal-confirm-delete'))

    await waitFor(() => expect(deleted).toEqual(['addr-1']))
    expect(onDeleted).toHaveBeenCalledWith('addr-1')
  })
})
