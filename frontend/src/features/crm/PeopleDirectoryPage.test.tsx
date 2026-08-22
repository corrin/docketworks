import { http, HttpResponse } from 'msw'
import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PaginatedPersonSummaryList, PersonSummary } from '@/api'
import { queryAutoId } from '@/test/auto-id'
import { renderWithProviders } from '@/test/render'
import { server } from '@/test/msw'
import { PeopleDirectoryPage } from './PeopleDirectoryPage'

const person = (overrides: Partial<PersonSummary> = {}): PersonSummary => ({
  id: 'p-1',
  name: 'Alex Smith',
  email: 'alex@example.com',
  is_active: true,
  primary_phone: '021 555 111',
  companies: [{ company_id: 'c-1', company_name: 'Alpha Engineering' }],
  ...overrides,
})

const paginated = (results: PersonSummary[]): PaginatedPersonSummaryList => ({
  count: results.length,
  page: 1,
  page_size: 50,
  results,
  total_pages: 1,
})

describe('PeopleDirectoryPage', () => {
  it('lists each person with phone and joined company names', async () => {
    server.use(
      http.get('*/api/people/', () =>
        HttpResponse.json(
          paginated([
            person(),
            person({
              id: 'p-2',
              name: 'Bo Chen',
              email: null,
              primary_phone: '',
              companies: [
                { company_id: 'c-1', company_name: 'Alpha Engineering' },
                { company_id: 'c-2', company_name: 'Beta Fabrication' },
              ],
            }),
          ]),
        ),
      ),
    )
    renderWithProviders(<PeopleDirectoryPage />)

    expect(await screen.findByText('Alex Smith')).toBeVisible()
    expect(screen.getByText('Alpha Engineering, Beta Fabrication')).toBeVisible()
    expect(screen.getByText('021 555 111')).toBeVisible()
    expect(queryAutoId('PeopleDirectory-row-p-1')).not.toBeNull()
    expect(screen.getAllByRole('button', { name: 'Manage' })).toHaveLength(2)
    // Complete result set: no truncation line.
    expect(queryAutoId('PeopleDirectory-truncation')).toBeNull()
  })

  it('says the list is truncated when more people exist than were returned', async () => {
    server.use(
      http.get('*/api/people/', () =>
        HttpResponse.json({ ...paginated([person()]), count: 1036, total_pages: 21 }),
      ),
    )
    renderWithProviders(<PeopleDirectoryPage />)

    expect(await screen.findByText('Alex Smith')).toBeVisible()
    expect(queryAutoId('PeopleDirectory-truncation')).toHaveTextContent(
      'Showing the first 1 of 1036 people',
    )
  })

  it('applies the search on Enter, not per keystroke', async () => {
    const queries: (string | null)[] = []
    server.use(
      http.get('*/api/people/', ({ request }) => {
        queries.push(new URL(request.url).searchParams.get('q'))
        return HttpResponse.json(paginated([person()]))
      }),
    )
    const { user } = renderWithProviders(<PeopleDirectoryPage />)
    await screen.findByText('Alex Smith')

    const search = screen.getByPlaceholderText('Search people...')
    await user.type(search, 'alex')
    expect(queries).toEqual([null])

    await user.type(search, '{Enter}')
    await waitFor(() => expect(queries).toEqual([null, 'alex']))
  })

  it('marks archived people and only them', async () => {
    server.use(
      http.get('*/api/people/', () =>
        HttpResponse.json(
          paginated([person(), person({ id: 'p-2', name: 'Bo Chen', is_active: false })]),
        ),
      ),
    )
    renderWithProviders(<PeopleDirectoryPage />)

    expect(await screen.findByText('Bo Chen')).toBeVisible()
    expect(queryAutoId('PeopleDirectory-archived-badge-p-2')).not.toBeNull()
    expect(queryAutoId('PeopleDirectory-archived-badge-p-1')).toBeNull()
  })

  it('requests archived people when the filter is checked', async () => {
    const includeArchived: (string | null)[] = []
    server.use(
      http.get('*/api/people/', ({ request }) => {
        includeArchived.push(new URL(request.url).searchParams.get('include_archived'))
        return HttpResponse.json(paginated([person()]))
      }),
    )
    const { user } = renderWithProviders(<PeopleDirectoryPage />)
    await screen.findByText('Alex Smith')

    await user.click(screen.getByLabelText('Show archived'))
    await waitFor(() => expect(includeArchived).toEqual([null, 'true']))
  })
})
