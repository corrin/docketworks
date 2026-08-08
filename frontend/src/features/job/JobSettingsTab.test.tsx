import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { XeroPayItemOut } from '@/api'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { JobSettingsTab } from './JobSettingsTab'

const payItem: XeroPayItemOut = {
  created_at: '2026-08-08T00:00:00Z',
  id: 'pay-1',
  multiplier: null,
  name: 'Ordinary Time',
  updated_at: '2026-08-08T00:00:00Z',
  uses_leave_api: false,
  xero_id: null,
  xero_last_modified: null,
  xero_last_synced: null,
  xero_tenant_id: null,
}

describe('JobSettingsTab', () => {
  it('does not claim initialization on failure and offers a working retry', async () => {
    let attempts = 0
    server.use(
      http.get('*/api/xero/pay-items/', () => {
        attempts += 1
        return attempts === 1
          ? HttpResponse.json({ detail: 'unavailable' }, { status: 503 })
          : HttpResponse.json([payItem])
      }),
    )
    const { container, user } = renderWithProviders(
      <JobSettingsTab job={{ default_xero_pay_item_id: null }} />,
    )
    await screen.findByRole('status')
    const root = container.querySelector('[data-initialized]')

    expect(root).toHaveAttribute('data-initialized', 'false')
    expect(await screen.findByRole('alert')).toHaveTextContent('Pay items could not be loaded')
    expect(root).toHaveAttribute('data-initialized', 'false')

    await user.click(screen.getByRole('button', { name: 'Try again' }))

    await screen.findByRole('option', { name: 'Ordinary Time' })
    await waitFor(() => expect(root).toHaveAttribute('data-initialized', 'true'))
  })
})
