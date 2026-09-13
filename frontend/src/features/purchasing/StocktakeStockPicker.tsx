import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'

import { purchasingStockSearchRetrieveInfiniteOptions, type StockItem } from '@/api'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/features/shared/SearchInput'
import { LoadMoreSentinel } from '@/features/shared/LoadMoreSentinel'
import { nextPageParam } from '@/features/shared/nextPageParam'
import { ListTable } from '@/features/shared/ListTable'
import { useDebouncedValue, SEARCH_DEBOUNCE_MS } from '@/features/shared/useDebouncedValue'
import { formatQuantity } from '@/lib/format'

export function StocktakeStockPicker({
  onSelect,
  selected,
}: {
  onSelect: (stock: StockItem) => void
  selected: ReadonlySet<string>
}) {
  const [search, setSearch] = useState('')
  const [location, setLocation] = useState('')
  const query = useDebouncedValue(search, SEARCH_DEBOUNCE_MS)
  const place = useDebouncedValue(location, SEARCH_DEBOUNCE_MS)
  const stock = useInfiniteQuery({
    ...purchasingStockSearchRetrieveInfiniteOptions({
      query: { q: query, location: place, countable: true },
    }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    refetchOnWindowFocus: false,
  })
  const rows = stock.data?.pages.flatMap((page) => page.results)
  const lastPage = stock.data?.pages.at(-1)
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <SearchInput
          value={search}
          onChange={setSearch}
          label="Search stock"
          placeholder="Search workshop stock"
          automationId="StocktakePicker-search"
        />
        <SearchInput
          value={location}
          onChange={setLocation}
          label="Location"
          placeholder="Filter location"
          automationId="StocktakePicker-location"
        />
      </div>
      <ListTable
        isPending={stock.isPending}
        isError={stock.isError}
        onRetry={() => void stock.refetch()}
        loadingLabel="Searching stock…"
        errorLabel="Unable to search stock."
        emptyLabel="No matching workshop stock. Use Add found item for new material."
        rows={rows}
        wrapperClassName="max-h-64"
        head={
          <tr>
            <th scope="col" className="p-2 text-left">
              Item
            </th>
            <th scope="col" className="p-2 text-left">
              Location
            </th>
            <th scope="col" className="p-2">
              Recorded
            </th>
            <th scope="col" className="p-2">
              Count
            </th>
          </tr>
        }
        footer={
          rows !== undefined &&
          lastPage !== undefined && (
            <LoadMoreSentinel
              automationId="StocktakePicker-load-more"
              noun="stock items"
              shown={rows.length}
              total={lastPage.count}
              hasNextPage={stock.hasNextPage}
              isFetchingNextPage={stock.isFetchingNextPage}
              isFetchNextPageError={stock.isFetchNextPageError}
              onLoadMore={() => void stock.fetchNextPage()}
            />
          )
        }
        renderRow={(item) => (
          <tr key={item.id}>
            <td className="p-2">{item.description}</td>
            <td className="p-2">{item.location}</td>
            <td className="p-2">{formatQuantity(Number(item.quantity))}</td>
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
    </section>
  )
}
