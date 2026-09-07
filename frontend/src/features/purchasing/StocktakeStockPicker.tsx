import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { stocktakeStockListOptions, type StocktakeStockOut } from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { ListTable } from '@/features/shared/ListTable'
import { useDebouncedValue, SEARCH_DEBOUNCE_MS } from '@/features/shared/useDebouncedValue'
import { trimDecimal } from '@/features/shared/decimal'

export function StocktakeStockPicker({
  onSelect,
  selected,
}: {
  onSelect: (stock: StocktakeStockOut) => void
  selected: ReadonlySet<string>
}) {
  const [search, setSearch] = useState('')
  const [location, setLocation] = useState('')
  const [page, setPage] = useState(1)
  const query = useDebouncedValue(search, SEARCH_DEBOUNCE_MS)
  const place = useDebouncedValue(location, SEARCH_DEBOUNCE_MS)
  const stock = useQuery(stocktakeStockListOptions({ query: { q: query, location: place, page } }))
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <label>
          Search stock
          <input
            className={INPUT_CLASS}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setPage(1)
            }}
          />
        </label>
        <label>
          Location
          <input
            className={INPUT_CLASS}
            value={location}
            onChange={(event) => {
              setLocation(event.target.value)
              setPage(1)
            }}
          />
        </label>
      </div>
      <ListTable
        isPending={stock.isPending}
        isError={stock.isError}
        onRetry={() => void stock.refetch()}
        loadingLabel="Searching stock…"
        errorLabel="Unable to search stock."
        emptyLabel="No matching workshop stock. Use Add found item for new material."
        rows={stock.data?.results}
        wrapperClassName="max-h-64"
        head={
          <tr>
            <th className="p-2 text-left">Item</th>
            <th className="p-2 text-left">Location</th>
            <th className="p-2">Recorded</th>
            <th className="p-2">Count</th>
          </tr>
        }
        renderRow={(item) => (
          <tr key={item.id}>
            <td className="p-2">{item.description}</td>
            <td className="p-2">{item.location}</td>
            <td className="p-2">{trimDecimal(String(item.quantity))}</td>
            <td className="p-2">
              <Button
                variant="outline"
                size="sm"
                disabled={selected.has(item.id)}
                onClick={() => onSelect(item)}
              >
                {selected.has(item.id) ? 'Added' : 'Add to count'}
              </Button>
            </td>
          </tr>
        )}
      />
      {stock.data && (
        <div className="flex items-center gap-3">
          <span>{stock.data.count} stock items</span>
          <Button variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Previous items
          </Button>
          <Button
            variant="outline"
            disabled={page * 50 >= stock.data.count}
            onClick={() => setPage(page + 1)}
          >
            Next items
          </Button>
        </div>
      )}
    </section>
  )
}
