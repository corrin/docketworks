import {
  useMutation,
  useQuery,
  useInfiniteQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { toast } from 'sonner'
import {
  apiErrorMessage,
  jobJobsCostSetsRetrieveOptions,
  costLineStockMovementRetrieveOptions,
  stockMovementsListOptions,
  stockMovementsListInfiniteOptions,
  purchasingStockListOptions,
  purchasingStockSearchRetrieveOptions,
  stocktakeMovementsListInfiniteOptions,
  stockMovementReturnMutation,
  type StockMovementPage,
} from '@/api'
import { invalidateJobViews } from '@/features/job'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { ListTable } from '@/features/shared/ListTable'
import { LoadMoreSentinel } from '@/features/shared/LoadMoreSentinel'
import { nextPageParam } from '@/features/shared/nextPageParam'
import { formatDateTime, formatQuantity } from '@/lib/format'

export function CostLineMovementHistory({ costLineId }: { costLineId: string }) {
  const movement = useQuery(costLineStockMovementRetrieveOptions({ path: { id: costLineId } }))
  return (
    <QueryState
      isPending={movement.isPending}
      isError={movement.isError}
      onRetry={() => void movement.refetch()}
      loadingLabel="Loading job material…"
      errorLabel="Unable to load job material history."
    >
      {movement.data && <StockMovementHistory stockId={movement.data.stock_id} />}
    </QueryState>
  )
}

export function StockMovementHistory({ stockId }: { stockId: string }) {
  const history = useInfiniteQuery({
    ...stockMovementsListInfiniteOptions({ path: { id: stockId } }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    refetchOnWindowFocus: false,
  })
  return <MovementRows history={history} />
}
export function StocktakeMovementHistory({ countId }: { countId: string }) {
  const history = useInfiniteQuery({
    ...stocktakeMovementsListInfiniteOptions({ path: { id: countId } }),
    initialPageParam: 1,
    getNextPageParam: nextPageParam,
    refetchOnWindowFocus: false,
  })
  return <MovementRows history={history} />
}
function MovementRows({
  history,
}: {
  history: UseInfiniteQueryResult<InfiniteData<StockMovementPage>>
}) {
  const rows = history.data?.pages.flatMap((page) => page.results)
  const lastPage = history.data?.pages.at(-1)
  const cache = useQueryClient()
  const reverse = useMutation(stockMovementReturnMutation())
  return (
    <>
      <ListTable
        isPending={history.isPending}
        isError={history.isError}
        onRetry={() => void history.refetch()}
        rows={rows}
        loadingLabel="Loading movements…"
        errorLabel="Unable to load stock history."
        emptyLabel="No movements recorded."
        wrapperClassName="max-h-[55vh]"
        head={
          <tr>
            <th scope="col" className="p-2 text-left">
              Recorded
            </th>
            <th scope="col" className="p-2 text-left">
              Item
            </th>
            <th scope="col" className="p-2">
              Before → after
            </th>
            <th scope="col" className="p-2 text-left">
              Counterpart
            </th>
            <th scope="col" className="p-2 text-left">
              Reason / operator
            </th>
            <th scope="col" className="p-2">
              Action
            </th>
          </tr>
        }
        footer={
          rows !== undefined &&
          lastPage !== undefined && (
            <LoadMoreSentinel
              automationId="StockHistory-load-more"
              noun="movements"
              shown={rows.length}
              total={lastPage.count}
              hasNextPage={history.hasNextPage}
              isFetchingNextPage={history.isFetchingNextPage}
              isFetchNextPageError={history.isFetchNextPageError}
              onLoadMore={() => void history.fetchNextPage()}
            />
          )
        }
        renderRow={(movement) => (
          <tr key={movement.id} className="border-b">
            <td className="p-2">{formatDateTime(movement.recorded_at)}</td>
            <td className="p-2">{movement.description}</td>
            <td className="p-2">
              {formatQuantity(movement.quantity_before)} → {formatQuantity(movement.quantity_after)}
            </td>
            <td className="p-2">
              {movement.counterpart_job_id === null ? (
                movement.counterpart_name
              ) : (
                <Link
                  className="text-blue-700 underline"
                  to="/jobs/$jobId"
                  params={{ jobId: movement.counterpart_job_id }}
                >
                  {movement.counterpart_name}
                </Link>
              )}
            </td>
            <td className="p-2">
              {movement.reason}
              <br />
              {movement.actor}
            </td>
            <td className="p-2">
              {movement.can_return && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={reverse.isPending}
                  onClick={() =>
                    reverse.mutate(
                      { path: { id: movement.id } },
                      {
                        onSuccess: () => {
                          toast.success('Material returned')
                          if (movement.counterpart_job_id !== null) {
                            void invalidateJobViews(cache, movement.counterpart_job_id)
                            void cache.invalidateQueries({
                              queryKey: jobJobsCostSetsRetrieveOptions({
                                path: { job_id: movement.counterpart_job_id, kind: 'actual' },
                              }).queryKey,
                            })
                          }
                          void cache.invalidateQueries({
                            queryKey: stockMovementsListOptions({ path: { id: movement.stock_id } })
                              .queryKey,
                          })
                          void cache.invalidateQueries({
                            queryKey: purchasingStockListOptions().queryKey,
                          })
                          void cache.invalidateQueries({
                            queryKey: purchasingStockSearchRetrieveOptions().queryKey,
                          })
                        },
                        onError: (error) =>
                          toast.error(apiErrorMessage(error, 'Unable to return material.')),
                      },
                    )
                  }
                >
                  Return issue
                </Button>
              )}
            </td>
          </tr>
        )}
      />
    </>
  )
}
