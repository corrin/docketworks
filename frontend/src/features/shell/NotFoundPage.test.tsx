import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'
import { NotFoundPage } from './NotFoundPage'

describe('NotFoundPage', () => {
  it('carries the automation id the E2E contract locates it by', async () => {
    const { container } = renderWithProviders(<NotFoundPage />)

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeVisible()
    expect(container.querySelector('[data-automation-id="NotFound-page"]')).not.toBeNull()
  })
})
