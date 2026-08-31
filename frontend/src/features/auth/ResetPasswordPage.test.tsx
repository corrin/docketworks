import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { ResetPasswordPage } from './ResetPasswordPage'

const CONFIRM = '*/api/accounts/password-reset/confirm/'

describe('ResetPasswordPage', () => {
  it('shows the invalid-link state when the URL is missing its parameters', async () => {
    renderWithProviders(<ResetPasswordPage uid="" token="" />)

    expect(await screen.findByText(/This reset link is incomplete/)).toBeInTheDocument()
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
  })

  it('refuses mismatched passwords locally, without a request', async () => {
    const { user } = renderWithProviders(<ResetPasswordPage uid="abc" token="tok" />)

    await user.type(await screen.findByLabelText('New password'), 'Fresh-Pass-9!')
    await user.type(screen.getByLabelText('Confirm new password'), 'Different-Pass-9!')
    await user.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The passwords do not match.')
  })

  it('renders the server 400 detail — the dead-link or weak-password reason', async () => {
    server.use(
      http.post(CONFIRM, () =>
        HttpResponse.json(
          { detail: 'This reset link is invalid or has expired.' },
          { status: 400 },
        ),
      ),
    )
    const { user } = renderWithProviders(<ResetPasswordPage uid="abc" token="tok" />)

    await user.type(await screen.findByLabelText('New password'), 'Fresh-Pass-9!')
    await user.type(screen.getByLabelText('Confirm new password'), 'Fresh-Pass-9!')
    await user.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This reset link is invalid or has expired.',
    )
  })
})
