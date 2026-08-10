import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { purchasingStockListOptions, purchasingStockSearchRetrieveOptions } from '@/api'
import type { StockItem } from '@/api'
import { trimDecimal } from '@/features/job/costing/calc'
import { formatCurrency } from '@/lib/format'

const SEARCH_DEBOUNCE_MS = 300
const MIN_QUERY_LENGTH = 3

/**
 * The stock page: the full active-stock list on load, swapped for
 * server-side FTS results once the (debounced) query reaches 3 characters.
 * Clearing the box must render the still-cached list query WITHOUT any
 * request to /search/ — the search query is enabled-gated, and the list
 * query never unmounts, so neither refetches on clear.
 */
export function StockPage() {
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setQuery(searchInput), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [searchInput])

  const searchActive = query.trim().length >= MIN_QUERY_LENGTH
  const list = useQuery(purchasingStockListOptions())
  const search = useQuery({
    ...purchasingStockSearchRetrieveOptions({ query: { q: query } }),
    enabled: searchActive,
  })

  const rows: readonly StockItem[] | undefined = searchActive ? search.data?.results : list.data

  return (
    <div className="min-h-screen p-6">
      <h1 className="text-xl font-bold text-gray-900">Stock</h1>

      <div className="mt-4">
        <input
          type="text"
          placeholder="Search stock items..."
          value={searchInput}
          autoComplete="off"
          data-automation-id="StockView-search"
          className="w-full max-w-md rounded-md border border-gray-300 px-3 py-2 focus:border-transparent focus:ring-2 focus:ring-blue-500"
          onChange={(event) => setSearchInput(event.target.value)}
        />
      </div>

      {(searchActive ? search.isError : list.isError) && (
        <div className="mt-8 text-red-600">Failed to load stock items. Reload the page.</div>
      )}

      {rows === undefined ? (
        <div className="mt-8 text-gray-500">Loading stock items...</div>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-gray-500">
                <th scope="col" className="px-3 py-2">
                  Code
                </th>
                {/* Description must stay the SECOND column: the wire contract
                    reads tbody td:nth-child(2). */}
                <th scope="col" className="px-3 py-2">
                  Description
                </th>
                <th scope="col" className="px-3 py-2">
                  Metal
                </th>
                <th scope="col" className="px-3 py-2">
                  Alloy
                </th>
                <th scope="col" className="px-3 py-2">
                  Spec
                </th>
                <th scope="col" className="px-3 py-2">
                  Location
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Quantity
                </th>
                <th scope="col" className="px-3 py-2 text-right">
                  Unit Cost
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.id} className="border-b border-gray-100 hover:bg-blue-50">
                  <td className="px-3 py-2">{item.item_code}</td>
                  <td className="px-3 py-2 font-medium text-gray-900">{item.description}</td>
                  <td className="px-3 py-2">{item.metal_type}</td>
                  <td className="px-3 py-2">{item.alloy}</td>
                  <td className="px-3 py-2">{item.specifics}</td>
                  <td className="px-3 py-2">{item.location}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {trimDecimal(item.quantity)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatCurrency(Number(item.unit_cost))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="mt-8 text-center text-gray-500">No stock items found</div>
          )}
        </div>
      )}
    </div>
  )
}
