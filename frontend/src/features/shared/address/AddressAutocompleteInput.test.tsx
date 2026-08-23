import { useState } from 'react'
import { screen, waitFor } from '@testing-library/react'
import { delay, http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { AddressCandidate } from '@/api'
import { queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { AddressAutocompleteInput } from './AddressAutocompleteInput'

const VALIDATE = '*/api/companies/addresses/validate/'

/** The one field the proxy takes, read without asserting the body's shape. */
async function addressOf(request: Request): Promise<string> {
  const body: unknown = await request.json()
  if (typeof body !== 'object' || body === null || !('address' in body)) {
    throw new Error('validate request carried no address')
  }
  return String(body.address)
}

function candidate(street: string): AddressCandidate {
  return {
    formatted_address: `${street}, Hillsborough, Auckland 1042, New Zealand`,
    street,
    suburb: 'Hillsborough',
    city: 'Auckland',
    state: '',
    postal_code: '1042',
    country: 'New Zealand',
    google_place_id: `place-${street}`,
    latitude: -36.9,
    longitude: 174.7,
  }
}

function Harness({ onSelect }: { onSelect: (candidate: AddressCandidate) => void }) {
  return <ControlledInput onSelect={onSelect} />
}

// A small controlled owner, as the modal is: the input never holds its own value.
function ControlledInput({ onSelect }: { onSelect: (candidate: AddressCandidate) => void }) {
  const [value, setValue] = useState('')
  return (
    <AddressAutocompleteInput
      value={value}
      onChange={setValue}
      onSelectCandidate={(chosen) => {
        setValue(chosen.street)
        onSelect(chosen)
      }}
    />
  )
}

describe('AddressAutocompleteInput', () => {
  it('does not ask the server until three characters are typed', async () => {
    const requests: string[] = []
    server.use(
      http.post(VALIDATE, async ({ request }) => {
        requests.push(await addressOf(request))
        return HttpResponse.json({ candidates: [] })
      }),
    )
    const { user } = renderWithProviders(<Harness onSelect={vi.fn()} />)
    const input = await screen.findByRole('combobox')

    await user.type(input, '7C')
    await new Promise((resolve) => setTimeout(resolve, 450))

    expect(requests).toEqual([])
  })

  it('offers the candidates once typing pauses, and Enter selects the highlighted one', async () => {
    const requests: string[] = []
    server.use(
      http.post(VALIDATE, async ({ request }) => {
        requests.push(await addressOf(request))
        return HttpResponse.json({ candidates: [candidate('7C Aldersgate Road')] })
      }),
    )
    const onSelect = vi.fn()
    const { user } = renderWithProviders(<Harness onSelect={onSelect} />)
    const input = await screen.findByRole('combobox')

    await user.type(input, '7C Aldersgate')
    await screen.findByText(/7C Aldersgate Road, Hillsborough/)
    // One round trip for the whole word, not one per keystroke.
    expect(requests).toEqual(['7C Aldersgate'])

    await user.keyboard('{Enter}')

    expect(onSelect).toHaveBeenCalledWith(candidate('7C Aldersgate Road'))
    expect(queryAutoId('AddressAutocompleteInput-suggestions')).toBeNull()
    expect(input).toHaveValue('7C Aldersgate Road')
  })

  it('a slow earlier answer never overwrites the latest one', async () => {
    server.use(
      http.post(VALIDATE, async ({ request }) => {
        if ((await addressOf(request)) === '7C Ald') {
          await delay(700)
          return HttpResponse.json({ candidates: [candidate('7C Alderman Avenue')] })
        }
        return HttpResponse.json({ candidates: [candidate('7C Aldersgate Road')] })
      }),
    )
    const { user } = renderWithProviders(<Harness onSelect={vi.fn()} />)
    const input = await screen.findByRole('combobox')

    await user.type(input, '7C Ald')
    await new Promise((resolve) => setTimeout(resolve, 350))
    await user.type(input, 'ersgate')

    await screen.findByText(/7C Aldersgate Road/)
    await new Promise((resolve) => setTimeout(resolve, 800))
    await waitFor(() => expect(screen.queryByText(/Alderman Avenue/)).toBeNull())
    expect(screen.getByText(/7C Aldersgate Road/)).toBeInTheDocument()
  })
})
