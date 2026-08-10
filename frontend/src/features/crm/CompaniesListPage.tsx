import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronDown, ChevronUp } from 'lucide-react'

import { companiesSearchRetrieveOptions } from '@/api'
import { ListTable } from '@/features/shared/ListTable'
import { useDebouncedValue } from '@/features/shared/useDebouncedValue'
import { formatCurrency } from '@/lib/format'

// v1's page size; the report is a first-page-plus-search view, not a pager —
// pagination controls ship with the slice that asserts on them.
const PAGE_SIZE = 20
const SEARCH_DEBOUNCE_MS = 300

type SortColumn = 'name' | 'total_spend'
type SortDir = 'asc' | 'desc'

interface SortHeaderProps {
  column: SortColumn
  label: string
  automationId: string
  sortBy: SortColumn
  sortDir: SortDir
  align: 'left' | 'right'
  onSort: (column: SortColumn) => void
}

function SortHeader({
  column,
  label,
  automationId,
  sortBy,
  sortDir,
  align,
  onSort,
}: SortHeaderProps) {
  const active = sortBy === column
  return (
    <th
      scope="col"
      data-automation-id={automationId}
      aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className="p-0"
    >
      {/* The button fills the cell so a click anywhere on the header (which
          is what the E2E spec targets) lands on a keyboard-operable control. */}
      <button
        type="button"
        className={`w-full cursor-pointer px-3 py-2 select-none hover:text-gray-900 ${
          align === 'right' ? 'text-right' : 'text-left'
        }`}
        onClick={() => onSort(column)}
      >
        {label}
        {active &&
          (sortDir === 'asc' ? (
            <ChevronUp className="ml-1 inline h-3 w-3" />
          ) : (
            <ChevronDown className="ml-1 inline h-3 w-3" />
          ))}
      </button>
    </th>
  )
}

/**
 * Companies report: server-sorted, server-searched list. Sorting happens in
 * the query params, never client-side — the first page of a client-side sort
 * would only reorder the 20 rows it happens to hold.
 */
export function CompaniesListPage() {
  const navigate = useNavigate()
  const [searchInput, setSearchInput] = useState('')
  const query = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS)
  const [sortBy, setSortBy] = useState<SortColumn>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const companies = useQuery({
    ...companiesSearchRetrieveOptions({
      query: { q: query, page: 1, page_size: PAGE_SIZE, sort_by: sortBy, sort_dir: sortDir },
    }),
    // Sort and search change the query key; without placeholder data every
    // change would unmount the table and re-flash the loading text.
    placeholderData: keepPreviousData,
  })

  const handleSort = (column: SortColumn) => {
    if (column === sortBy) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(column)
      setSortDir('asc')
    }
  }

  return (
    <div className="min-h-screen p-6">
      <h1 className="text-xl font-bold text-gray-900">Companies</h1>

      <div className="mt-4">
        <input
          type="text"
          data-automation-id="CompaniesTable-search"
          placeholder="Search companies..."
          value={searchInput}
          autoComplete="off"
          className="w-full max-w-md rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
          onChange={(event) => setSearchInput(event.target.value)}
        />
      </div>

      <ListTable
        isPending={companies.isPending}
        isError={companies.isError}
        onRetry={() => void companies.refetch()}
        loadingLabel="Loading companies..."
        errorLabel="Failed to load companies."
        rows={companies.data?.results}
        emptyLabel="No companies found"
        automationId="CompaniesTable-table"
        head={
          <tr className="border-b border-gray-200 text-gray-500">
            <SortHeader
              column="name"
              label="Name"
              automationId="CompaniesTable-header-name"
              sortBy={sortBy}
              sortDir={sortDir}
              align="left"
              onSort={handleSort}
            />
            <th scope="col" className="px-3 py-2 text-left">
              Email
            </th>
            <th scope="col" className="px-3 py-2 text-left">
              Phone
            </th>
            <SortHeader
              column="total_spend"
              label="Total Spend"
              automationId="CompaniesTable-header-total-spend"
              sortBy={sortBy}
              sortDir={sortDir}
              align="right"
              onSort={handleSort}
            />
          </tr>
        }
        renderRow={(company) => (
          <tr
            key={company.id}
            data-automation-id={`CompaniesTable-row-${company.id}`}
            data-company-id={company.id}
            className="cursor-pointer border-b border-gray-100 hover:bg-blue-50"
            onClick={() => {
              void navigate({
                to: '/crm/companies/$companyId',
                params: { companyId: company.id },
              })
            }}
          >
            <td
              data-automation-id={`CompaniesTable-cell-${company.id}-name`}
              className="px-3 py-2 font-medium text-gray-900"
            >
              {/* A real link so keyboard users can open the detail page;
                  the row onClick is the mouse-only whole-row affordance. */}
              <Link
                to="/crm/companies/$companyId"
                params={{ companyId: company.id }}
                className="hover:underline"
                onClick={(event) => event.stopPropagation()}
              >
                {company.name}
              </Link>
            </td>
            <td className="px-3 py-2">{company.email}</td>
            <td className="px-3 py-2">{company.phone}</td>
            <td
              data-automation-id={`CompaniesTable-cell-${company.id}-total-spend`}
              className="px-3 py-2 text-right"
            >
              {formatCurrency(company.total_spend)}
            </td>
          </tr>
        )}
      />
    </div>
  )
}
