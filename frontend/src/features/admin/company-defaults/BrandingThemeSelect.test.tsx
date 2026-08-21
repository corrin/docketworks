import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'

import type { SettingsFieldOut, XeroBrandingThemeOut } from '@/api'
import { autoId, queryAutoId } from '@/test/auto-id'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'

import { BrandingThemeSelect } from './BrandingThemeSelect'

const BRANDING_THEMES = '*/api/xero/branding-themes/'
const AUTOMATION_ID = 'CompanyDefaultsPage-xero-field-xero_sales_branding_theme_id'

const field: SettingsFieldOut = {
  help_text: '',
  key: 'xero_sales_branding_theme_id',
  label: 'Branding theme',
  read_only: false,
  required: false,
  section: 'xero',
  type: 'xero_branding_theme',
}

function theme(overrides: Partial<XeroBrandingThemeOut> = {}): XeroBrandingThemeOut {
  return { external_id: 'theme-1', is_default: false, name: 'Standard', ...overrides }
}

function renderSelect(value: string | null, onChange = vi.fn()) {
  return {
    onChange,
    ...renderWithProviders(
      <BrandingThemeSelect field={field} value={value} onChange={onChange} section="xero" />,
    ),
  }
}

describe('BrandingThemeSelect', () => {
  it('shows a disabled loading placeholder before the themes arrive', async () => {
    server.use(http.get(BRANDING_THEMES, () => new Promise(() => {}))) // never resolves
    renderSelect(null)
    // renderWithProviders resolves the route asynchronously, so even a state
    // that never changes again needs an await for the first paint.
    await waitFor(() => expect(autoId(AUTOMATION_ID)).toBeInTheDocument())
    const select = autoId(AUTOMATION_ID)
    expect(select).toBeDisabled()
    expect(select).toHaveTextContent('Loading Xero branding themes…')
  })

  it('renders the typed 401 as "Xero is not connected." without a toast', async () => {
    server.use(
      http.get(BRANDING_THEMES, () =>
        HttpResponse.json(
          { message: 'Xero is not connected', redirect_to_auth: true, success: false },
          { status: 401 },
        ),
      ),
    )
    renderSelect(null)
    // Wait for the error marker itself, not just "disabled" — the loading
    // state is disabled too, so that alone would pass before the request settles.
    await waitFor(() => expect(queryAutoId(`${AUTOMATION_ID}-error`)).toBeInTheDocument())
    expect(autoId(AUTOMATION_ID)).toBeDisabled()
    expect(autoId(`${AUTOMATION_ID}-error`)).toHaveTextContent('Xero is not connected.')
    expect(screen.queryByText(/could not load branding themes/i)).not.toBeInTheDocument()
  })

  it('renders a generic load failure for a non-401 error', async () => {
    server.use(
      http.get(BRANDING_THEMES, () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    )
    renderSelect(null)
    await waitFor(() => expect(queryAutoId(`${AUTOMATION_ID}-error`)).toBeInTheDocument())
    expect(autoId(AUTOMATION_ID)).toBeDisabled()
    expect(autoId(`${AUTOMATION_ID}-error`)).toHaveTextContent(
      'Could not load branding themes from Xero.',
    )
  })

  it('renders the empty state when Xero has no themes', async () => {
    server.use(http.get(BRANDING_THEMES, () => HttpResponse.json([])))
    renderSelect(null)
    await waitFor(() => expect(queryAutoId(`${AUTOMATION_ID}-empty`)).toBeInTheDocument())
    expect(autoId(AUTOMATION_ID)).toBeDisabled()
  })

  it('lists themes with the Xero-default suffix and enables the select', async () => {
    server.use(
      http.get(BRANDING_THEMES, () =>
        HttpResponse.json([
          theme({ external_id: 'a', name: 'Standard', is_default: true }),
          theme({ external_id: 'b', name: 'Alt' }),
        ]),
      ),
    )
    renderSelect(null)
    await waitFor(() => expect(autoId(AUTOMATION_ID)).not.toBeDisabled())
    expect(screen.getByRole('option', { name: 'Standard (Xero default)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Alt' })).toBeInTheDocument()
    expect(queryAutoId(`${AUTOMATION_ID}-error`)).not.toBeInTheDocument()
    expect(queryAutoId(`${AUTOMATION_ID}-empty`)).not.toBeInTheDocument()
  })

  it('shows the setup-incomplete placeholder when no theme is configured yet', async () => {
    server.use(http.get(BRANDING_THEMES, () => HttpResponse.json([theme()])))
    renderSelect(null)
    await waitFor(() => expect(autoId(AUTOMATION_ID)).not.toBeDisabled())
    expect(
      screen.getByRole('option', { name: 'Xero setup incomplete — select a branding theme' }),
    ).toBeInTheDocument()
  })

  it('keeps a stale theme id selectable as "Unavailable theme" rather than dropping it', async () => {
    server.use(http.get(BRANDING_THEMES, () => HttpResponse.json([theme({ external_id: 'a' })])))
    renderSelect('deleted-theme')
    await waitFor(() => expect(autoId(AUTOMATION_ID)).not.toBeDisabled())
    expect(
      screen.getByRole('option', { name: 'Unavailable theme (deleted-theme)' }),
    ).toBeInTheDocument()
    expect(autoId(AUTOMATION_ID)).toHaveValue('deleted-theme')
  })

  it('never writes an empty selection back — selecting a theme is a one-way completion of Xero setup', async () => {
    server.use(http.get(BRANDING_THEMES, () => HttpResponse.json([theme({ external_id: 'a' })])))
    const onChange = vi.fn()
    const { user } = renderSelect(null, onChange)
    await waitFor(() => expect(autoId(AUTOMATION_ID)).not.toBeDisabled())
    await user.selectOptions(autoId(AUTOMATION_ID), 'a')
    expect(onChange).toHaveBeenCalledWith('a')

    onChange.mockClear()
    // The placeholder option is disabled, so userEvent cannot reach an empty
    // selection through the real UI — but that's exactly the gap a deleted
    // `next === ''` guard would leave unexercised. fireEvent bypasses the
    // disabled-option restriction to drive the change handler directly and
    // prove the guard itself does the ignoring, not just that users can't reach it.
    fireEvent.change(autoId(AUTOMATION_ID), { target: { value: '' } })
    expect(onChange).not.toHaveBeenCalled()
  })
})
