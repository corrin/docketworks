import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { ListTable } from './ListTable'

interface Row {
  id: string
  name: string
}

const baseProps = {
  loadingLabel: 'Loading things...',
  errorLabel: 'Failed to load things.',
  emptyLabel: 'No things found',
  head: (
    <tr>
      <th>Name</th>
    </tr>
  ),
  renderRow: (row: Row) => (
    <tr key={row.id} data-automation-id={`Row-${row.id}`}>
      <td>{row.name}</td>
    </tr>
  ),
}

describe('ListTable', () => {
  it('renders the loading label while pending, with its automation id if given', async () => {
    renderWithProviders(
      <ListTable
        {...baseProps}
        isPending
        isError={false}
        rows={undefined}
        loadingAutomationId="Thing-loading"
      />,
    )
    expect(await screen.findByText('Loading things...')).toHaveAttribute(
      'data-automation-id',
      'Thing-loading',
    )
  })

  it('renders the error label with a Retry button when onRetry is given', async () => {
    const onRetry = vi.fn()
    const { user } = renderWithProviders(
      <ListTable {...baseProps} isPending={false} isError rows={undefined} onRetry={onRetry} />,
    )
    expect(await screen.findByText('Failed to load things.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('falls back to a static reload message when onRetry is omitted', async () => {
    renderWithProviders(<ListTable {...baseProps} isPending={false} isError rows={undefined} />)
    expect(await screen.findByText(/Reload the page\./)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })

  it('renders one row per item via renderRow', async () => {
    const rows: Row[] = [
      { id: '1', name: 'First' },
      { id: '2', name: 'Second' },
    ]
    const { container } = renderWithProviders(
      <ListTable {...baseProps} isPending={false} isError={false} rows={rows} />,
    )
    expect(await screen.findByText('First')).toBeVisible()
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
    expect(screen.getByText('Second')).toBeVisible()
  })

  it('renders the empty label when rows resolve to an empty array', async () => {
    renderWithProviders(<ListTable {...baseProps} isPending={false} isError={false} rows={[]} />)
    expect(await screen.findByText('No things found')).toBeVisible()
  })

  it('does not render extra content while pending', async () => {
    renderWithProviders(
      <ListTable {...baseProps} isPending isError={false} rows={undefined}>
        <div>Summary cards</div>
      </ListTable>,
    )
    await screen.findByText('Loading things...')
    expect(screen.queryByText('Summary cards')).toBeNull()
  })

  it('renders extra content above the table once rows are ready', async () => {
    renderWithProviders(
      <ListTable {...baseProps} isPending={false} isError={false} rows={[]}>
        <div>Summary cards</div>
      </ListTable>,
    )
    expect(await screen.findByText('Summary cards')).toBeVisible()
  })
})
