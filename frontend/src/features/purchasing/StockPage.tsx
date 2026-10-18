import { useState } from 'react'
import { useMutation, useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  stocktakeCreateMutation,
  purchasingStockDestroyMutation,
  purchasingStockListOptions,
  purchasingStockSearchRetrieveOptions,
  apiErrorMessage,
} from '@/api'
import { Button } from '@/components/ui/button'
import { StockMovementHistory, CostLineMovementHistory } from './StockMovementHistory'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'

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

export function StockPage({ costLineId, stockId }: { costLineId?: string; stockId?: string }) {
  const { t } = useTranslation('purchasing')
  const cache = useQueryClient()
  const retire = useMutation(purchasingStockDestroyMutation())
  const [includeInactive, setIncludeInactive] = useState(false)
  const navigate = useNavigate()
  const createCount = useMutation(stocktakeCreateMutation())
  const recordCount = (countStockId?: string) =>
    createCount.mutate(
      { body: { stock_id: countStockId ?? null } },
      {
        onSuccess: (count) =>
          void navigate({
            to: '/purchasing/stocktakes/$stocktakeId',
            params: { stocktakeId: count.id },
          }),
        onError: (error) => toast.error(apiErrorMessage(error, t('stock.setupFirst'))),
      },
    )
  const [searchInput, setSearchInput] = useState('')
  const query = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS)

  const activeQuery = useInfiniteQuery({
    ...purchasingStockListInfiniteOptions({
      query: {
        q: query.trim().length >= MIN_SEARCH_TERM_LENGTH ? query : '',
        include_inactive: includeInactive,
      },
    }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    refetchOnWindowFocus: false,
  })
  const rows = activeQuery.data?.pages.flatMap((page) => page.results)
  const lastPage = activeQuery.data?.pages.at(-1)

  return (
    <div className="min-h-screen p-6 text-sm">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-gray-900">{t('stock.title')}</h1>
        <Button disabled={createCount.isPending} onClick={() => recordCount()}>
          {t('stock.recordFound')}
        </Button>
      </div>

      <div className="mt-4">
        <SearchInput
          value={searchInput}
          onChange={setSearchInput}
          placeholder={t('stock.searchPlaceholder')}
          automationId="StockView-search"
          label={t('stock.searchLabel')}
        />
      </div>

      <label className="mt-3 flex items-center gap-2">
        <input
          type="checkbox"
          checked={includeInactive}
          onChange={(event) => setIncludeInactive(event.target.checked)}
        />
        {t('stock.includeRetired')}
      </label>
      <ListTable
        isPending={activeQuery.isPending}
        isError={activeQuery.isError}
        onRetry={() => void activeQuery.refetch()}
        loadingLabel={t('stock.loading')}
        errorLabel={t('stock.loadFailed')}
        rows={rows}
        automationId="StockView-table"
        wrapperClassName="max-h-[60vh]"
        emptyLabel={t('stock.empty')}
        head={
          <tr className="border-b border-gray-200 text-left text-gray-500">
            <th scope="col" className="px-3 py-2">
              {t('stock.header.code')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('stock.header.description')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('stock.header.metal')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('stock.header.alloy')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('stock.header.spec')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('stock.header.location')}
            </th>
            <th scope="col" className="px-3 py-2 text-right">
              {t('stock.header.quantity')}
            </th>
            <th scope="col" className="px-3 py-2 text-right">
              {t('stock.header.unitCost')}
            </th>
            <th scope="col" className="px-3 py-2">
              {t('stock.header.count')}
            </th>
          </tr>
        }
        footer={
          rows !== undefined &&
          lastPage !== undefined && (
            <LoadMoreSentinel
              automationId="StockView-load-more"
              noun={t('stock.noun')}
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
                  {t('stock.recordCount')}
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  void navigate({ to: '/purchasing/stock', search: { stockId: item.id } })
                }
              >
                {t('stock.history')}
              </Button>
              {item.can_retire && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={retire.isPending}
                  onClick={() =>
                    retire.mutate(
                      { path: { id: item.id } },
                      {
                        onSuccess: () => {
                          toast.success(t('stock.retired'))
                          void cache.invalidateQueries({
                            queryKey: purchasingStockListOptions().queryKey,
                          })
                          void cache.invalidateQueries({
                            queryKey: purchasingStockSearchRetrieveOptions().queryKey,
                          })
                        },
                        onError: (error) =>
                          toast.error(apiErrorMessage(error, t('stock.retireFailed'))),
                      },
                    )
                  }
                >
                  {t('stock.retire')}
                </Button>
              )}
              {!item.is_active && <span className="text-gray-500">{t('stock.retiredBadge')}</span>}
            </td>
          </tr>
        )}
      />
      <Drawer
        open={stockId !== undefined || costLineId !== undefined}
        onOpenChange={(open) => {
          if (!open) void navigate({ to: '/purchasing/stock', search: {} })
        }}
      >
        <DrawerContent>
          <div className="mx-auto w-full max-w-6xl p-4">
            <DrawerHeader>
              <DrawerTitle>{t('stock.drawerTitle')}</DrawerTitle>
              <DrawerDescription>{t('stock.drawerDescription')}</DrawerDescription>
            </DrawerHeader>
            {stockId !== undefined ? (
              <StockMovementHistory stockId={stockId} />
            ) : (
              costLineId !== undefined && <CostLineMovementHistory costLineId={costLineId} />
            )}
            <DrawerClose asChild>
              <Button variant="outline">{t('stock.closeHistory')}</Button>
            </DrawerClose>
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  )
}
