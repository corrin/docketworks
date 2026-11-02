import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { HoursInput } from './HoursInput'

describe('HoursInput', () => {
  // Every hours field is this one: a number input here would refuse "4h"
  // on the drawer and the fill sheet again.
  it('reads "4h" as he types it and when he leaves the field', async () => {
    const onHoursChange = vi.fn()
    const onCommit = vi.fn()
    const user = userEvent.setup()
    render(
      <HoursInput
        hours={null}
        aria-label="Hours"
        onHoursChange={onHoursChange}
        onCommit={onCommit}
      />,
    )

    await user.type(screen.getByLabelText('Hours'), '4h')
    expect(onHoursChange).toHaveBeenLastCalledWith(4)
    await user.tab()
    expect(onCommit).toHaveBeenCalledWith(4)
  })

  it('commits on Enter and shows the hours in words once left', async () => {
    const onCommit = vi.fn()
    const user = userEvent.setup()
    render(<HoursInput hours={3.5} aria-label="Hours" onCommit={onCommit} />)

    const field = screen.getByLabelText('Hours')
    expect(field).toHaveValue('3h 30m')
    await user.clear(field)
    await user.type(field, '1 1/4{Enter}')
    expect(onCommit).toHaveBeenCalledWith(1.25)
    // The parent has not taken the new hours, so the stored ones show again.
    expect(field).toHaveValue('3h 30m')
  })

  it('shows hours set from outside even while he is in the field', async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <HoursInput hours={null} aria-label="Hours" onHoursChange={vi.fn()} />,
    )

    await user.type(screen.getByLabelText('Hours'), '0.5')
    // A chip sets the hours; focus has not left the field.
    rerender(<HoursInput hours={1} aria-label="Hours" onHoursChange={vi.fn()} />)
    expect(screen.getByLabelText('Hours')).toHaveValue('1h')
  })
})
