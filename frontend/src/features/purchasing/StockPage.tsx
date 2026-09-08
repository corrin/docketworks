import { useState } from 'react'
import { useMutation, useInfiniteQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'
import { stocktakeCreateMutation, apiErrorMessage } from '@/api'
import { Button } from '@/components/ui/button'
import { StockMovementHistory, CostLineMovementHistory } from './StockMovementHistory'
import { EntryGridSection } from '@/features/shared/EntryGridSection'

import { purchasingStockListInfiniteOptions } from '@/api'
import { LoadMoreSentinel } from '@/features/shared/LoadMoreSentinel'
import { nextPageParam } from '@/features/shared/nextPageParam'
import { ListTable } from '@/features/shared/ListTable'
import {
  MIN_SEARCH_TERM_LENGTH,
  SEARCH_DEBOUNCE_MS,
  useDebouncedValue,
} from '@/features/shared/useDebouncedValue'
import { formatCurrency, formatQuantity } from '@/lib/format'
import { SearchInput } from '@/features/shared/SearchInput'

export function StockPage({ costLineId }: { costLineId?: string }) {
  const [historyId, setHistoryId] = useState<string | null>(null)
  const navigate = useNavigate()
  const createCount = useMutation(stocktakeCreateMutation())
  const recordCount = (stockId: string) =>
    createCount.mutate(
      { body: { stock_id: stockId } },
      {
        onSuccess: (count) =>
          void navigate({
            to: '/purchasing/stocktakes/$stocktakeId',
            params: { stocktakeId: count.id },
          }),
        onError: (error) =>
          toast.error(
            apiErrorMessage(error, 'Open Purchases → Stocktake to complete setup first.'),
          ),
      },
    )
  const [searchInput, setSearchInput] = useState('')
  const query = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS)

  const activeQuery = useInfiniteQuery({
    ...purchasingStockListInfiniteOptions({
      query: { q: query.trim().length >= MIN_SEARCH_TERM_LENGTH ? query : '' },
    }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    refetchOnWindowFocus: false,
  })
  const rows = activeQuery.data?.pages.flatMap((page) => page.results)
  const lastPage = activeQuery.data?.pages.at(-1)

  return (
    <div className="min-h-screen p-6">
      <h1 className="text-xl font-bold text-gray-900">Stock</h1>

      <div className="mt-4">
        <SearchInput
          value={searchInput}
          onChange={setSearchInput}
          placeholder="Search stock items..."
          automationId="StockView-search"
          label="Search stock items"
        />
      </div>

      <ListTable
        isPending={activeQuery.isPending}
        isError={activeQuery.isError}
        onRetry={() => void activeQuery.refetch()}
        loadingLabel="Loading stock items..."
        errorLabel="Failed to load stock items."
        rows={rows}
        automationId="StockView-table"
        wrapperClassName="max-h-[60vh]"
        emptyLabel="No stock items found"
        head={
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th scope="col" className="px-3 py-2">
              Code
            </th>
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
            <th scope="col" className="px-3 py-2">
              Count
            </th>
          </tr>
        }
        footer={
          rows !== undefined &&
          lastPage !== undefined && (
            <LoadMoreSentinel
              automationId="StockView-load-more"
              noun="stock items"
              shown={rows.length}
              total={lastPage.count}
              hasNextPage={activeQuery.hasNextPage}
              isFetchingNextPage={activeQuery.isFetchingNextPage}
              isFetchNextPageError={activeQuery.isFetchNextPageError}
              onLoadMore={() => void activeQuery.fetchNextPage()}
            />
          )
        }
        renderRow={(item) => (
          <tr key={item.id} className="border-b border-gray-100 hover:bg-blue-50">
            <td className="px-3 py-2">{item.item_code}</td>
            <td
              data-automation-id="StockView-description"
              className="px-3 py-2 font-medium text-gray-900"
            >
              {item.description}
            </td>
            <td className="px-3 py-2">{item.metal_type}</td>
            <td className="px-3 py-2">{item.alloy}</td>
            <td className="px-3 py-2">{item.specifics}</td>
            <td className="px-3 py-2">{item.location}</td>
            <td
              data-automation-id="StockView-quantity"
              className="px-3 py-2 text-right tabular-nums"
            >
              {formatQuantity(Number(item.quantity))}
            </td>
            <td className="px-3 py-2 text-right tabular-nums">
              {formatCurrency(Number(item.unit_cost))}
            </td>
            <td className="px-3 py-2">
              {item.can_count && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={createCount.isPending}
                  onClick={() => recordCount(item.id)}
                >
                  Record count
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={() => setHistoryId(item.id)}>
                History
              </Button>
            </td>
          </tr>
        )}
      />
      {costLineId !== undefined && (
        <EntryGridSection title="Job material history">
          <CostLineMovementHistory costLineId={costLineId} />
        </EntryGridSection>
      )}
      {historyId !== null && (
        <EntryGridSection
          title="Stock movements"
          actions={
            <Button variant="ghost" onClick={() => setHistoryId(null)}>
              Close history
            </Button>
          }
        >
          <StockMovementHistory stockId={historyId} />
        </EntryGridSection>
      )}
    </div>
  )
}
