import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PersonCompanyLink, PersonDetail } from '@/api'
import { queryAutoId } from '@/test/auto-id'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { PersonDetailPage } from './PersonDetailPage'

const activeLink: PersonCompanyLink = {
  company_id: 'c-1',
  company_name: 'Alpha Engineering',
  position: 'Manager',
  is_primary: true,
  notes: null,
  is_active: true,
}

const inactiveLink: PersonCompanyLink = {
  company_id: 'c-2',
  company_name: 'Beta Fabrication',
  position: null,
  is_primary: false,
  notes: 'left in 2025',
  is_active: false,
}

const personDetail = (overrides: Partial<PersonDetail> = {}): PersonDetail => ({
  id: 'p-1',
  name: 'Alex Smith',
  email: 'alex@example.com',
  is_active: true,
  primary_phone: '021 555 111',
  companies: [{ company_id: 'c-1', company_name: 'Alpha Engineering' }],
  company_links: [activeLink],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

function stubPerson(detail: PersonDetail, links: PersonCompanyLink[]) {
  server.use(
    http.get('*/api/people/p-1/', () => HttpResponse.json(detail)),
    http.get('*/api/people/p-1/contact-methods/', () => HttpResponse.json([])),
    http.get('*/api/people/p-1/company-links/', () => HttpResponse.json(links)),
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('PersonDetailPage', () => {
  it('shows an inactive link and restores it with its stored fields', async () => {
    let putBody: unknown = null
    stubPerson(personDetail(), [activeLink, inactiveLink])
    server.use(
      http.put('*/api/people/p-1/company-links/c-2/', async ({ request }) => {
        putBody = await request.json()
        return HttpResponse.json({ ...inactiveLink, is_active: true })
      }),
    )
    const { user } = renderWithProviders(<PersonDetailPage personId="p-1" />)

    expect(await screen.findByText('Beta Fabrication')).toBeVisible()
    const linkCard = queryAutoId('PersonDetail-company-link-c-2')
    expect(linkCard).toHaveTextContent('Inactive')

    await user.click(screen.getByRole('button', { name: 'Restore' }))
    await waitFor(() =>
      expect(putBody).toEqual({ position: null, notes: 'left in 2025', is_primary: false }),
    )
    expect(await screen.findByText('Company link restored')).toBeVisible()
  })

  it('saves identity with only name and email in the body', async () => {
    let patchBody: unknown = null
    stubPerson(personDetail(), [activeLink])
    server.use(
      http.patch('*/api/people/p-1/', async ({ request }) => {
        patchBody = await request.json()
        return HttpResponse.json(personDetail({ name: 'Alexandra Smith' }))
      }),
    )
    const { user } = renderWithProviders(<PersonDetailPage personId="p-1" />)

    const name = await screen.findByLabelText('Name')
    await user.clear(name)
    await user.type(name, 'Alexandra Smith')
    await user.click(screen.getByRole('button', { name: 'Save identity' }))

    await waitFor(() =>
      expect(patchBody).toEqual({ name: 'Alexandra Smith', email: 'alex@example.com' }),
    )
  })

  it('surfaces a blocked unlink and keeps the link active', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    stubPerson(personDetail(), [activeLink])
    server.use(
      http.delete('*/api/people/p-1/company-links/c-1/', () =>
        HttpResponse.json(
          { detail: 'Removing this link would make Alex conflict with Beta Fabrication' },
          { status: 400 },
        ),
      ),
    )
    const { user } = renderWithProviders(<PersonDetailPage personId="p-1" />)

    await screen.findByText('Alpha Engineering')
    await user.click(screen.getByRole('button', { name: 'Remove' }))

    expect(
      await screen.findByText('Removing this link would make Alex conflict with Beta Fabrication'),
    ).toBeVisible()
    expect(queryAutoId('PersonDetail-company-link-c-1')).toHaveTextContent('Active')
  })

  it('archives an active person and shows the badge from the refetch', async () => {
    let archived = false
    server.use(
      http.get('*/api/people/p-1/', () =>
        HttpResponse.json(personDetail({ is_active: !archived })),
      ),
      http.get('*/api/people/p-1/contact-methods/', () => HttpResponse.json([])),
      http.get('*/api/people/p-1/company-links/', () =>
        HttpResponse.json([{ ...activeLink, is_active: !archived }]),
      ),
      http.post('*/api/people/p-1/archive/', () => {
        archived = true
        return HttpResponse.json(personDetail({ is_active: false }))
      }),
    )
    const { user } = renderWithProviders(<PersonDetailPage personId="p-1" />)

    await user.click(await screen.findByRole('button', { name: 'Archive person' }))

    await waitFor(() => expect(queryAutoId('PersonDetail-archived-badge')).not.toBeNull())
  })

  it('offers no archive button for an archived person', async () => {
    stubPerson(personDetail({ is_active: false }), [
      { ...activeLink, is_active: false, is_primary: false },
    ])
    renderWithProviders(<PersonDetailPage personId="p-1" />)

    expect(await screen.findByText('Alpha Engineering')).toBeVisible()
    expect(queryAutoId('PersonDetail-archived-badge')).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'Archive person' })).toBeNull()
  })
})
