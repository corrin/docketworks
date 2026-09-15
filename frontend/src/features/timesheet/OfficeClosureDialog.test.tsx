import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { autoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { OfficeClosureDialog } from './OfficeClosureDialog'

/** A parent that opens the dialog on demand, the way the leave page does. */
function Host() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Reopen
      </button>
      <OfficeClosureDialog
        open={open}
        onOpenChange={setOpen}
        onSaved={vi.fn(() => Promise.resolve())}
        publicHolidayName="Public Holiday"
      />
    </>
  )
}

describe('OfficeClosureDialog', () => {
  it('starts every open from a fresh form, dates and preview included', async () => {
    // The form state now lives in a body DialogContent unmounts on close. If
    // it moved back to the shell, an edited date and a loaded preview would
    // survive Cancel and greet the next open — the stale-preview hazard the
    // old reset effect existed to prevent, plus the dates it did not cover.
    server.use(
      http.post('*/api/timesheets/leave/office-closure/preview/', () =>
        HttpResponse.json({ available_staff: 2, available_hours: 16, staff: [] }),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<Host />)

    const startDate = await waitFor(() => autoId('OfficeClosureDialog-start-date'))
    const originalDate = startDate.getAttribute('value')
    await user.clear(startDate)
    await user.type(startDate, '2030-01-01')
    await user.click(autoId('OfficeClosureDialog-preview'))
    await waitFor(() => autoId('OfficeClosureDialog-preview-result'))

    await user.click(autoId('OfficeClosureDialog-cancel'))
    await waitFor(() =>
      expect(
        document.querySelector('[data-automation-id="OfficeClosureDialog-start-date"]'),
      ).toBeNull(),
    )
    await user.click(screen.getByRole('button', { name: 'Reopen' }))

    const reopened = await waitFor(() => autoId('OfficeClosureDialog-start-date'))
    expect(reopened.getAttribute('value')).toBe(originalDate)
    expect(
      document.querySelector('[data-automation-id="OfficeClosureDialog-preview-result"]'),
    ).toBeNull()
  })
})
