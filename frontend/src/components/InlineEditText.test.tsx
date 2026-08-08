import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { InlineEditText } from './InlineEditText'

describe('InlineEditText', () => {
  it('commits the trimmed value on Enter', async () => {
    const onCommit = vi.fn()
    const { user } = renderWithProviders(<InlineEditText value="Old name" onCommit={onCommit} />)

    await user.click(await screen.findByText('Old name'))
    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.type(input, '  New name  {Enter}')

    expect(onCommit).toHaveBeenCalledWith('New name')
    expect(await screen.findByText('Old name')).toBeVisible()
  })

  it('cancels on Escape without committing', async () => {
    const onCommit = vi.fn()
    const { user } = renderWithProviders(<InlineEditText value="Old name" onCommit={onCommit} />)

    await user.click(await screen.findByText('Old name'))
    await user.type(screen.getByRole('textbox'), 'discarded{Escape}')

    expect(onCommit).not.toHaveBeenCalled()
  })

  it('blocks an empty commit when required', async () => {
    const onCommit = vi.fn()
    const { user } = renderWithProviders(
      <InlineEditText value="Old name" required onCommit={onCommit} />,
    )

    await user.click(await screen.findByText('Old name'))
    const input = screen.getByRole('textbox')
    await user.clear(input)
    await user.keyboard('{Enter}')

    expect(onCommit).not.toHaveBeenCalled()
  })
})
