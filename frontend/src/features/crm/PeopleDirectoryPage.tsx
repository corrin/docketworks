import { useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'

import { peopleListOptions, peopleListQueryKey, type CompanySearchResult } from '@/api'
import { CompanyLookup } from '@/features/shared/company/CompanyLookup'
import { PersonSelector, type SelectedPerson } from '@/features/shared/company/PersonSelector'
import { ListTable } from '@/features/shared/ListTable'

const PAGE_SIZE = 50

/**
 * People directory: one identity per person, linked to every company they
 * work with.
 *
 * Fable: search is applied on Enter or the Search button, not debounced like
 * CompaniesListPage — the directory filters on name, email, phone digits and
 * company name, and a half-typed phone number matching everything is noise,
 * not feedback.
 */
export function PeopleDirectoryPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchInput, setSearchInput] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [createCompany, setCreateCompany] = useState<CompanySearchResult | null>(null)
  const [createPerson, setCreatePerson] = useState<SelectedPerson | null>(null)

  // First-page-plus-search, like CompaniesListPage: nothing in the app pages
  // through results — search is how a person is found, so no pager renders.
  const people = useQuery({
    ...peopleListOptions({
      query: {
        q: appliedQuery || undefined,
        include_archived: includeArchived || undefined,
        page: 1,
        page_size: PAGE_SIZE,
      },
    }),
    placeholderData: keepPreviousData,
  })

  const applySearch = () => {
    if (searchInput === appliedQuery) {
      // Same query: no state change, so no new query key — the user
      // pressing Search again is asking for fresh data.
      void people.refetch()
      return
    }
    setAppliedQuery(searchInput)
  }

  return (
    <div className="min-h-screen p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">People</h1>
          <p className="mt-1 text-sm text-gray-600">
            One identity per person, linked to every company they work with.
          </p>
        </div>
        <button
          type="button"
          data-automation-id="PeopleDirectory-create"
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          onClick={() => {
            setShowCreate((current) => !current)
            setCreateCompany(null)
            setCreatePerson(null)
          }}
        >
          {showCreate ? 'Close' : 'Add person'}
        </button>
      </div>

      {showCreate && (
        <div
          data-automation-id="PeopleDirectory-create-panel"
          className="mt-4 max-w-xl rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
        >
          <p className="text-sm text-gray-600">
            Pick or create the company first; the person is created with that company link.
          </p>
          <div className="mt-3 space-y-4">
            <CompanyLookup
              id="people-directory-company"
              label="Company"
              selectedCompany={createCompany}
              onSelectCompany={(company) => {
                setCreateCompany(company)
                setCreatePerson(null)
              }}
            />
            {createCompany && (
              <PersonSelector
                id="people-directory-person"
                label="Person"
                companyId={createCompany.id}
                companyName={createCompany.name}
                selectedPerson={createPerson}
                autoSelectPrimary={false}
                onSelectPerson={(person) => {
                  if (person === null) {
                    setCreatePerson(null)
                    return
                  }
                  setShowCreate(false)
                  setCreateCompany(null)
                  setCreatePerson(null)
                  void queryClient.invalidateQueries({ queryKey: peopleListQueryKey() })
                }}
              />
            )}
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          type="text"
          data-automation-id="PeopleDirectory-search"
          placeholder="Search people..."
          value={searchInput}
          autoComplete="off"
          className="w-full max-w-md rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
          onChange={(event) => setSearchInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              applySearch()
            }
          }}
        />
        <button
          type="button"
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          onClick={applySearch}
        >
          Search
        </button>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            data-automation-id="PeopleDirectory-show-archived"
            checked={includeArchived}
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            onChange={(event) => setIncludeArchived(event.target.checked)}
          />
          Show archived
        </label>
      </div>

      {people.isError && people.data !== undefined && (
        <div className="mt-4 flex items-center gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <span>Refresh failed — showing the last loaded page.</span>
          <button
            type="button"
            className="font-medium underline"
            onClick={() => void people.refetch()}
          >
            Retry
          </button>
        </div>
      )}
      <ListTable
        isPending={people.isPending}
        // A failed FIRST load is the error state; an errored background
        // refetch keeps the keepPreviousData table on screen, with the
        // refresh-failed banner above owning visibility.
        isError={people.isError && people.data === undefined}
        onRetry={() => void people.refetch()}
        loadingLabel="Loading people..."
        errorLabel="Failed to load people."
        rows={people.data?.results}
        emptyLabel="No people found"
        automationId="PeopleDirectory-table"
        head={
          <tr className="border-b border-gray-200 text-gray-500">
            <th scope="col" className="px-3 py-2 text-left">
              Person
            </th>
            <th scope="col" className="px-3 py-2 text-left">
              Phone
            </th>
            <th scope="col" className="px-3 py-2 text-left">
              Companies
            </th>
            <th scope="col" className="px-3 py-2 text-left">
              Action
            </th>
          </tr>
        }
        renderRow={(person) => (
          <tr
            key={person.id}
            data-automation-id={`PeopleDirectory-row-${person.id}`}
            className="border-b border-gray-100"
          >
            <td className="px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900">{person.name}</span>
                {!person.is_active && (
                  <span
                    data-automation-id={`PeopleDirectory-archived-badge-${person.id}`}
                    className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700"
                  >
                    Archived
                  </span>
                )}
              </div>
              {person.email && <div className="text-xs text-gray-500">{person.email}</div>}
            </td>
            <td className="px-3 py-2">{person.primary_phone || '—'}</td>
            <td className="px-3 py-2">
              {person.companies.map((company) => company.company_name).join(', ') || '—'}
            </td>
            <td className="px-3 py-2">
              <button
                type="button"
                data-automation-id={`PeopleDirectory-open-${person.id}`}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                onClick={() => {
                  void navigate({ to: '/crm/people/$personId', params: { personId: person.id } })
                }}
              >
                Manage
              </button>
            </td>
          </tr>
        )}
      />

      {people.data && people.data.count > people.data.results.length && (
        <p data-automation-id="PeopleDirectory-truncation" className="mt-4 text-sm text-gray-500">
          Showing the first {people.data.results.length} of {people.data.count} people — refine the
          search to find the rest.
        </p>
      )}
    </div>
  )
}
