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
    // Complete result set: the count is shown, the Load more button is not.
    expect(screen.getByText('Showing 2 of 2 people')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })

  it('appends the next page on Load more and stops at the last page', async () => {
    const pages: (string | null)[] = []
    server.use(
      http.get('*/api/people/', ({ request }) => {
        const page = new URL(request.url).searchParams.get('page')
        pages.push(page)
        if (page === '2') {
          return HttpResponse.json({
            ...paginated([person({ id: 'p-3', name: 'Cy Dube' })]),
            count: 3,
            page: 2,
            total_pages: 2,
          })
        }
        return HttpResponse.json({
          ...paginated([person(), person({ id: 'p-2', name: 'Bo Chen' })]),
          count: 3,
          total_pages: 2,
        })
      }),
    )
    const { user } = renderWithProviders(<PeopleDirectoryPage />)

    expect(await screen.findByText('Alex Smith')).toBeVisible()
    expect(screen.getByText('Showing 2 of 3 people')).toBeVisible()
    // The server's page size applies; the page does not carry its own.
    expect(pages).toEqual(['1'])

    await user.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('Cy Dube')).toBeVisible()
    expect(screen.getByText('Alex Smith')).toBeVisible()
    expect(screen.getByText('Showing 3 of 3 people')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    expect(pages).toEqual(['1', '2'])
  })

  it('keeps the loaded rows and offers a retry when the next page fails', async () => {
    let failNextPage = true
    server.use(
      http.get('*/api/people/', ({ request }) => {
        const page = new URL(request.url).searchParams.get('page')
        if (page === '2') {
          if (failNextPage) return HttpResponse.json({ detail: 'boom' }, { status: 500 })
          return HttpResponse.json({
            ...paginated([person({ id: 'p-2', name: 'Bo Chen' })]),
            count: 2,
            page: 2,
            total_pages: 2,
          })
        }
        return HttpResponse.json({ ...paginated([person()]), count: 2, total_pages: 2 })
      }),
    )
    const { user } = renderWithProviders(<PeopleDirectoryPage />)
    await screen.findByText('Alex Smith')

    await user.click(screen.getByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('Loading more failed.')).toBeVisible()
    expect(screen.getByText('Alex Smith')).toBeVisible()

    failNextPage = false
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Bo Chen')).toBeVisible()
    expect(screen.queryByText('Loading more failed.')).toBeNull()
  })

  it('keeps the rows and offers a retry when a background refresh fails', async () => {
    let calls = 0
    server.use(
      http.get('*/api/people/', () => {
        calls += 1
        if (calls === 2) return HttpResponse.json({ detail: 'boom' }, { status: 500 })
        return HttpResponse.json(paginated([person()]))
      }),
    )
    const { user } = renderWithProviders(<PeopleDirectoryPage />)
    await screen.findByText('Alex Smith')

    // Search with the same (empty) query is a refetch of what is on screen.
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('Refresh failed — showing the last loaded rows.')).toBeVisible()
    expect(screen.getByText('Alex Smith')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(screen.queryByText('Refresh failed — showing the last loaded rows.')).toBeNull(),
    )
    expect(calls).toBe(3)
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
