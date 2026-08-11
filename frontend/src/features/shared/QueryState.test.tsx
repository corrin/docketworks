import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { QueryState } from './QueryState'

describe('QueryState', () => {
  it('renders the loading label while pending, with its automation id if given', async () => {
    renderWithProviders(
      <QueryState
        isPending
        isError={false}
        loadingLabel="Loading things..."
        loadingAutomationId="Thing-loading"
        errorLabel="Failed to load things."
      >
        <div>Content</div>
      </QueryState>,
    )
    expect(await screen.findByText('Loading things...')).toHaveAttribute(
      'data-automation-id',
      'Thing-loading',
    )
    expect(screen.queryByText('Content')).toBeNull()
  })

  it('renders the error label with a Retry button when onRetry is given', async () => {
    const onRetry = vi.fn()
    const { user } = renderWithProviders(
      <QueryState
        isPending={false}
        isError
        onRetry={onRetry}
        loadingLabel="Loading things..."
        errorLabel="Failed to load things."
      >
        <div>Content</div>
      </QueryState>,
    )
    expect(await screen.findByText('Failed to load things.')).toBeVisible()
    expect(screen.queryByText('Content')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('falls back to a static reload message when onRetry is omitted', async () => {
    renderWithProviders(
      <QueryState
        isPending={false}
        isError
        loadingLabel="Loading things..."
        errorLabel="Failed to load things."
      >
        <div>Content</div>
      </QueryState>,
    )
    expect(await screen.findByText(/Reload the page\./)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })

  it('renders children once neither pending nor errored', async () => {
    renderWithProviders(
      <QueryState
        isPending={false}
        isError={false}
        loadingLabel="Loading things..."
        errorLabel="Failed to load things."
      >
        <div>Content</div>
      </QueryState>,
    )
    expect(await screen.findByText('Content')).toBeVisible()
  })
})
