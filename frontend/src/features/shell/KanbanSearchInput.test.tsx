/**
 * KAN-353: typing a job number into the navbar search box.
 *
 * The reported symptom was that "97537" became `"9"7537` in the box and the
 * board returned nothing. It needs a PAUSE after the first character — the
 * 300ms debounce has to fire mid-word — which is what ordinary typing looks
 * like and what the E2E specs' searchInput.fill() never does. fill() is one
 * atomic change event, so the intermediate single-character navigation that
 * corrupts the box never happens; that gap is why the suite stayed green.
 */
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SEARCH_DEBOUNCE_MS } from '@/features/shared/useDebouncedValue'
import { renderWithProviders } from '@/test/render'

import { KanbanSearchInput } from './KanbanSearchInput'

/** Long enough that the component's debounced navigation has certainly run. */
const PAST_DEBOUNCE_MS = SEARCH_DEBOUNCE_MS + 100

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

describe('KanbanSearchInput — typing a job number on the board', () => {
  it('does not corrupt the box when the debounce fires mid-word', async () => {
    const { user } = renderWithProviders(<KanbanSearchInput />, { initialPath: '/kanban' })
    const input = await screen.findByPlaceholderText<HTMLInputElement>('Search jobs...')

    await user.type(input, '9')
    await pause(PAST_DEBOUNCE_MS)
    // The box read back its own write here. With the raw-query-string read it
    // came back as `"9"` — quote characters included — and the rest of the
    // job number appended to that.
    expect(input.value).toBe('9')

    await user.type(input, '7537')
    await pause(PAST_DEBOUNCE_MS)

    expect(input.value).toBe('97537')
  })

  it('leaves a non-numeric term alone, as it always did', async () => {
    // The control: "smith" never matched the router's jsonStart pattern, so
    // it was written unquoted and was never affected. It must stay that way.
    const { user } = renderWithProviders(<KanbanSearchInput />, { initialPath: '/kanban' })
    const input = await screen.findByPlaceholderText<HTMLInputElement>('Search jobs...')

    await user.type(input, 's')
    await pause(PAST_DEBOUNCE_MS)
    await user.type(input, 'mith')
    await pause(PAST_DEBOUNCE_MS)

    expect(input.value).toBe('smith')
  })

  it('hydrates from a shared unquoted ?q=97537 link', async () => {
    // A person writes ?q=97537 by hand; the router parses it to a NUMBER.
    // Requiring a string dropped it, leaving an unfiltered board under a
    // search box that showed the query.
    renderWithProviders(<KanbanSearchInput />, { initialPath: '/kanban?q=97537' })

    const input = await screen.findByPlaceholderText<HTMLInputElement>('Search jobs...')
    await waitFor(() => expect(input.value).toBe('97537'))
  })
})
