import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { SupplierPickupAddressOut } from '@/api'
import { expectNoAccessibilityViolations } from '@/test/accessibility'
import { autoId, queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { PickupAddressSelector } from './PickupAddressSelector'

const SUPPLIER = { id: 'supplier-1', name: 'Metal Supplies Ltd' }
const LIST = '*/api/companies/pickup-addresses/'
const ONE = '*/api/companies/pickup-addresses/:id/'

const SELECTED: SupplierPickupAddressOut = {
  id: 'addr-1',
  company: SUPPLIER.id,
  name: 'Main yard',
  street: '1 Steel Road',
  suburb: null,
  city: 'Auckland',
  state: null,
  postal_code: null,
  country: 'New Zealand',
  google_place_id: null,
  latitude: null,
  longitude: null,
  is_primary: true,
  notes: null,
  is_active: true,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  formatted_address: '1 Steel Road, Auckland',
}

describe('PickupAddressSelector', () => {
  it('shows the chosen address and Clear hands back null', async () => {
    const onChange = vi.fn()
    const { user, container } = renderWithProviders(
      <PickupAddressSelector supplier={SUPPLIER} selected={SELECTED} onChange={onChange} />,
    )

    expect(await screen.findByLabelText('Pickup address')).toHaveValue('1 Steel Road, Auckland')
    await expectNoAccessibilityViolations(container)
    await user.click(autoId('PickupAddressSelector-clear-button'))

    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('offers no Clear while nothing is chosen, and the button opens the list', async () => {
    server.use(http.get(LIST, () => HttpResponse.json([])))
    const { user } = renderWithProviders(
      <PickupAddressSelector supplier={SUPPLIER} selected={null} onChange={vi.fn()} />,
    )

    expect(await screen.findByLabelText('Pickup address')).toHaveValue('')
    expect(queryAutoId('PickupAddressSelector-clear-button')).toBeNull()
    await user.click(autoId('PickupAddressSelector-modal-button'))

    expect(await screen.findByText(`Pickup address for ${SUPPLIER.name}`)).toBeInTheDocument()
  })

  it('editing the chosen address reaches the owner', async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json([SELECTED])),
      http.put(ONE, () => HttpResponse.json({ ...SELECTED, name: 'Back gate' })),
    )
    const onChange = vi.fn()
    const { user } = renderWithProviders(
      <PickupAddressSelector supplier={SUPPLIER} selected={SELECTED} onChange={onChange} />,
    )
    await screen.findByLabelText('Pickup address')
    await user.click(autoId('PickupAddressSelector-modal-button'))
    await screen.findByText('Main yard')

    await user.click(autoId('PickupAddressSelectionModal-edit-addr-1'))
    await user.click(autoId('PickupAddressSelectionModal-submit'))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ ...SELECTED, name: 'Back gate' }))
  })

  it('deleting the chosen address clears the selection', async () => {
    server.use(
      http.get(LIST, () => HttpResponse.json([SELECTED])),
      http.delete(ONE, () => new HttpResponse(null, { status: 204 })),
    )
    const onChange = vi.fn()
    const { user } = renderWithProviders(
      <PickupAddressSelector supplier={SUPPLIER} selected={SELECTED} onChange={onChange} />,
    )
    await screen.findByLabelText('Pickup address')
    await user.click(autoId('PickupAddressSelector-modal-button'))
    await screen.findByText('Main yard')

    await user.click(autoId('PickupAddressSelectionModal-delete-addr-1'))
    await user.click(await screen.findByRole('button', { name: 'Delete' }))

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null))
  })
})
