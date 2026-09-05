import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { autoId } from '@/test/auto-id'
import { renderWithProviders } from '@/test/render'

import { TabBar } from './TabBar'

const TABS = [
  { key: 'current', label: 'Current' },
  { key: 'past', label: 'Past' },
] as const

describe('TabBar', () => {
  it('marks exactly the active tab as selected', async () => {
    renderWithProviders(
      <TabBar tabs={TABS} activeKey="current" onChange={vi.fn()} idPrefix="Demo-tab" />,
    )
    await screen.findByText('Current')

    // Four call sites reach their tabs by automation id and two specs reach
    // CompanyDetail's by role; a refactor dropping either contract would strand
    // one of those groups, so both are asserted here rather than in each caller.
    expect(autoId('Demo-tab-current')).toHaveAttribute('aria-selected', 'true')
    expect(autoId('Demo-tab-past')).toHaveAttribute('aria-selected', 'false')
    expect(screen.getAllByRole('tab')).toHaveLength(2)
  })

  it('reports the clicked tab key rather than its label or index', async () => {
    const onChange = vi.fn()
    const { user } = renderWithProviders(
      <TabBar tabs={TABS} activeKey="current" onChange={onChange} idPrefix="Demo-tab" />,
    )
    await screen.findByText('Past')

    await user.click(autoId('Demo-tab-past'))

    expect(onChange).toHaveBeenCalledWith('past')
  })

  it('renders each label exactly once', async () => {
    // PhoneCallsPage asserts findAllByText('Recent Calls') === 2 — the tab plus
    // its queue heading. A hidden duplicate or a title= echo added here would
    // make that 3 and break a caller that never changed.
    renderWithProviders(
      <TabBar tabs={TABS} activeKey="current" onChange={vi.fn()} idPrefix="Demo-tab" />,
    )
    expect(await screen.findAllByText('Current')).toHaveLength(1)
  })
})
