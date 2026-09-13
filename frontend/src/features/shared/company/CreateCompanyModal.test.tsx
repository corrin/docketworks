import { waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import { autoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import { CreateCompanyModal } from './CreateCompanyModal'

describe('CreateCompanyModal', () => {
  it('refuses dismissal while the create is in flight', async () => {
    // The form lives in a body that unmounts on close. If the shell let a
    // dismissal through mid-request, the user could reopen a fresh form and
    // submit the same name again while the first create still runs — two
    // companies in Xero for one name — and the first completion would then
    // close the second dialog. The shell's `saving` is what makes both
    // unreachable, so this asserts it from the outside.
    server.use(http.post('*/api/companies/create/', () => new Promise(() => {})))
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(
      <CreateCompanyModal open initialName="Acme" onClose={onClose} onCreated={vi.fn()} />,
    )

    await user.click(await waitFor(() => autoId('CreateCompanyModal-submit')))
    await waitFor(() => expect(autoId('CreateCompanyModal-submit')).toBeDisabled())
    expect(autoId('CreateCompanyModal-cancel')).toBeDisabled()

    await user.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
    expect(autoId('CreateCompanyModal-name-input')).toBeInTheDocument()
  })
})
