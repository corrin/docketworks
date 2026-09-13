import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw'
import { renderWithProviders } from '@/test/render'
import type { ProviderOut } from '@/api'
import { AIProvidersSection } from './AIProvidersSection'

const URL = '*/api/ai/providers/'
const provider: ProviderOut = {
  id: 7,
  name: 'OpenAI',
  provider_type: 'OpenAI',
  model_name: 'test-model',
  default: false,
  has_api_key: true,
}

function load(rows: ProviderOut[] = [provider]) {
  server.use(http.get(URL, () => HttpResponse.json(rows)))
}

describe('AI provider administration', () => {
  it('keeps the stored key when editing metadata and preserves failed edits', async () => {
    load()
    const bodies: unknown[] = []
    server.use(
      http.patch(`${URL}7/`, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ detail: 'Save failed' }, { status: 400 })
      }),
    )
    const { user } = renderWithProviders(<AIProvidersSection />)
    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByLabelText('API key')).toHaveValue('')
    await user.clear(within(dialog).getByLabelText('Name'))
    await user.type(within(dialog).getByLabelText('Name'), 'Changed')
    await user.click(within(dialog).getByRole('button', { name: 'Save provider' }))
    await screen.findByRole('alert')
    expect(bodies).toEqual([{ name: 'Changed' }])
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Changed')
  })

  it('creates an OpenAI provider through the supported form', async () => {
    load([])
    const bodies: unknown[] = []
    server.use(
      http.post(URL, async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(provider, { status: 201 })
      }),
    )
    const { user } = renderWithProviders(<AIProvidersSection />)
    await user.click(await screen.findByRole('button', { name: 'Add provider' }))
    await user.type(screen.getByLabelText('Name'), 'OpenAI')
    await user.type(screen.getByLabelText('Model'), 'test-model')
    await user.type(screen.getByLabelText('API key'), 'new-secret')
    await user.click(screen.getByRole('button', { name: 'Save provider' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(bodies).toEqual([
      { name: 'OpenAI', provider_type: 'OpenAI', model_name: 'test-model', api_key: 'new-secret' },
    ])
  })

  it('tests the saved row only after an explicit click', async () => {
    load()
    let calls = 0
    server.use(
      http.post(`${URL}7/test/`, () => {
        calls += 1
        return HttpResponse.json({ model: 'openai/test-model' })
      }),
    )
    const { user } = renderWithProviders(<AIProvidersSection />)
    const button = await screen.findByRole('button', { name: 'Test provider' })
    expect(calls).toBe(0)
    await user.click(button)
    await waitFor(() => expect(calls).toBe(1))
  })
})
