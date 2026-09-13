import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { expectNoAccessibilityViolations } from '@/test/accessibility'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { PoHistorySection } from './PoHistorySection'

const EVENTS = '*/api/purchasing/purchase-orders/po-1/events/'

describe('PO notes and history', () => {
  it('retains an unsuccessful note and shows the persisted note after retry', async () => {
    let saved = false
    const note = {
      id: 'note-1',
      description: 'Collect on Thursday\nAsk for Sam.',
      staff: 'Office User',
      timestamp: '2026-09-06T04:00:00Z',
    }
    server.use(
      http.get(EVENTS, () => HttpResponse.json({ events: saved ? [note] : [] })),
      http.post(EVENTS, () =>
        HttpResponse.json({ detail: 'Note could not be saved' }, { status: 400 }),
      ),
    )
    const { user, container } = renderWithProviders(<PoHistorySection poId="po-1" />)
    await screen.findByText('No notes yet.')
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    const editor = screen.getByLabelText('Note')
    await user.type(editor, note.description)
    await user.click(screen.getByRole('button', { name: 'Save note' }))
    await screen.findByText('Note could not be saved')
    expect(editor).toHaveValue(note.description)
    server.use(
      http.post(EVENTS, async ({ request }) => {
        expect(await request.json()).toEqual({ description: note.description })
        saved = true
        return HttpResponse.json({ success: true, event: note }, { status: 201 })
      }),
    )
    await user.click(screen.getByRole('button', { name: 'Save note' }))
    await screen.findByText('Office User')
    expect(screen.getByText('Collect on Thursday Ask for Sam.')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByLabelText('Note')).not.toBeInTheDocument())
    await expectNoAccessibilityViolations(container)
  })

  it('shows a read failure with retry instead of an empty history', async () => {
    server.use(
      http.get(EVENTS, () => HttpResponse.json({ detail: 'Unavailable' }, { status: 400 })),
    )
    const { user } = renderWithProviders(<PoHistorySection poId="po-1" />)
    await screen.findByText('Could not load notes.')
    expect(screen.queryByText('No notes yet.')).not.toBeInTheDocument()
    server.use(http.get(EVENTS, () => HttpResponse.json({ events: [] })))
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('No notes yet.')
  })
})
