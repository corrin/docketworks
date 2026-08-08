import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { InlineEditSelect } from './InlineEditSelect'

const OPTIONS = [
  { key: 'draft', label: 'Draft' },
  { key: 'in_progress', label: 'In Progress' },
]

describe('InlineEditSelect', () => {
  it('shows the label, edits the key, and commits via confirm', async () => {
    const onCommit = vi.fn()
    const { container, user } = renderWithProviders(
      <InlineEditSelect
        automationId="JobView-status"
        value="draft"
        options={OPTIONS}
        onCommit={onCommit}
      />,
    )

    await screen.findByText('Draft')
    const display = container.querySelector('[data-automation-id="JobView-status-display"]')
    expect(display).toHaveTextContent('Draft')

    await user.click(screen.getByText('Draft'))
    await user.selectOptions(screen.getByRole('combobox'), 'in_progress')
    const confirm = container.querySelector('[data-automation-id="JobView-status-confirm"]')
    if (!(confirm instanceof HTMLElement)) {
      throw new Error('Confirm button did not render')
    }
    await user.click(confirm)

    expect(onCommit).toHaveBeenCalledWith('in_progress')
  })
})
