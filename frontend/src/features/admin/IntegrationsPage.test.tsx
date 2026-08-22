import { Link } from '@tanstack/react-router'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { IntegrationsPage } from './IntegrationsPage'

import type { IntegrationSettingsOut } from '@/api'
import { autoId } from '@/test/auto-id'

const SETTINGS = '*/api/integration-settings/'

function settings(overrides: Partial<IntegrationSettingsOut> = {}): IntegrationSettingsOut {
  return {
    id: 1,
    has_google_maps_api_key: true,
    has_phone_provider_username: false,
    has_phone_provider_password: false,
    phone_provider_enabled: false,
    phone_provider_recording_deletion_enabled: false,
    phone_provider_base_url: null,
    phone_provider_account_code: 'ACC-1',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

function mockLoad(body: IntegrationSettingsOut = settings()) {
  server.use(http.get(SETTINGS, () => HttpResponse.json(body)))
}

/** Records PATCH bodies and answers with the given row. */
function mockSave(response: IntegrationSettingsOut): unknown[] {
  const bodies: unknown[] = []
  server.use(
    http.patch(SETTINGS, async ({ request }) => {
      bodies.push(await request.json())
      return HttpResponse.json(response)
    }),
  )
  return bodies
}

async function renderPage() {
  // A real Link, so navigating away exercises the router blocker.
  const result = renderWithProviders(
    <>
      <IntegrationsPage />
      <Link to="/kanban">Leave this page</Link>
    </>,
  )
  await screen.findByText('Google')
  return result
}

const save = () => autoId('IntegrationsPage-save-button')
const cancel = () => autoId('IntegrationsPage-cancel-button')
const mapsKey = () => autoId('IntegrationsPage-google-field-google_maps_api_key')
const mapsStatus = () => autoId('IntegrationsPage-google-status-google_maps_api_key')
const accountCode = () => autoId('IntegrationsPage-phone-field-phone_provider_account_code')

describe('IntegrationsPage', () => {
  beforeEach(() => {
    mockLoad()
  })

  it('reports a stored secret without showing it, and disables Save until something changes', async () => {
    await renderPage()
    expect(mapsStatus()).toHaveTextContent('Configured')
    expect(mapsKey()).toHaveValue('')
    expect(autoId('IntegrationsPage-phone-status-phone_provider_password')).toHaveTextContent(
      'Not configured',
    )
    expect(save()).toBeDisabled()
    expect(cancel()).toBeDisabled()
  })

  it('replacing a secret sends only that field, and the page is clean afterwards', async () => {
    const bodies = mockSave(settings())
    const { user } = await renderPage()

    await user.type(mapsKey(), 'new-key')
    expect(mapsStatus()).toHaveTextContent('Will be replaced on save')
    await user.click(save())

    await waitFor(() => expect(bodies).toHaveLength(1))
    expect(bodies[0]).toEqual({ google_maps_api_key: 'new-key' })
    await waitFor(() => expect(save()).toBeDisabled())
    // The secret is not echoed back: the box empties and the status reflects the server.
    expect(mapsKey()).toHaveValue('')
    expect(mapsStatus()).toHaveTextContent('Configured')
  })

  it('Clear sends null, and the server answer drives the status', async () => {
    const bodies = mockSave(settings({ has_google_maps_api_key: false }))
    const { user } = await renderPage()

    await user.click(autoId('IntegrationsPage-google-clear-google_maps_api_key'))
    expect(mapsStatus()).toHaveTextContent('Will be cleared on save')
    await user.click(save())

    await waitFor(() => expect(bodies).toEqual([{ google_maps_api_key: null }]))
    await waitFor(() => expect(mapsStatus()).toHaveTextContent('Not configured'))
  })

  it('an emptied text box is sent as null, never as a blank string', async () => {
    const bodies = mockSave(settings({ phone_provider_account_code: null }))
    const { user } = await renderPage()

    await user.clear(accountCode())
    await user.click(save())

    await waitFor(() => expect(bodies).toEqual([{ phone_provider_account_code: null }]))
  })

  it('Cancel restores the loaded values and re-disables Save', async () => {
    const { user } = await renderPage()
    await user.type(mapsKey(), 'scratch')
    await user.clear(accountCode())
    await user.type(accountCode(), 'ACC-2')
    expect(save()).toBeEnabled()

    await user.click(cancel())
    expect(mapsKey()).toHaveValue('')
    expect(accountCode()).toHaveValue('ACC-1')
    expect(save()).toBeDisabled()
  })

  it('a failed save keeps the edits and surfaces the server message', async () => {
    server.use(
      http.patch(SETTINGS, () =>
        HttpResponse.json(
          { detail: 'phone_provider_base_url: Enter a valid URL.' },
          { status: 400 },
        ),
      ),
    )
    const { user } = await renderPage()
    await user.click(autoId('IntegrationsPage-phone-field-phone_provider_enabled'))
    await user.click(save())

    expect(await screen.findByText(/Enter a valid URL/)).toBeInTheDocument()
    expect(autoId('IntegrationsPage-phone-field-phone_provider_enabled')).toBeChecked()
    expect(save()).toBeEnabled()
  })

  it('asks for confirmation before leaving with unsaved changes, and stays when refused', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { user } = await renderPage()
    await user.type(mapsKey(), 'scratch')

    await user.click(screen.getByRole('link', { name: 'Leave this page' }))

    expect(confirm).toHaveBeenCalledWith(
      'You have unsaved changes. Discard them and leave this page?',
    )
    expect(mapsKey()).toBeInTheDocument()
    confirm.mockRestore()
  })
})
