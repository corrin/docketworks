import {
  useMutation,
  useQuery,
  useInfiniteQuery,
  useQueryClient,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation('purchasing')
  const movement = useQuery(costLineStockMovementRetrieveOptions({ path: { id: costLineId } }))
  return (
    <QueryState
      isPending={movement.isPending}
      isError={movement.isError}
      onRetry={() => void movement.refetch()}
      loadingLabel={t('movements.jobMaterialLoading')}
      errorLabel={t('movements.jobMaterialLoadFailed')}
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
  const { t } = useTranslation('purchasing')
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
        loadingLabel={t('movements.loading')}
        errorLabel={t('movements.loadFailed')}
        emptyLabel={t('movements.empty')}
        wrapperClassName="max-h-[55vh]"
        head={
          <tr>
            <th scope="col" className="p-2 text-left" title={t('movements.titles.recorded')}>
              {t('movements.header.recorded')}
            </th>
            <th scope="col" className="p-2 text-left">
              {t('movements.header.item')}
            </th>
            <th scope="col" className="p-2" title={t('movements.titles.beforeAfter')}>
              {t('movements.header.beforeAfter')}
            </th>
            <th scope="col" className="p-2 text-left" title={t('movements.titles.counterpart')}>
              {t('movements.header.counterpart')}
            </th>
            <th scope="col" className="p-2 text-left" title={t('movements.titles.reasonOperator')}>
              {t('movements.header.reasonOperator')}
            </th>
            <th scope="col" className="p-2">
              {t('movements.header.action')}
            </th>
          </tr>
        }
        footer={
          rows !== undefined &&
          lastPage !== undefined && (
            <LoadMoreSentinel
              automationId="StockHistory-load-more"
              noun={t('movements.noun')}
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
                  title={t('movements.returnIssueTitle')}
                  onClick={() =>
                    reverse.mutate(
                      { path: { id: movement.id } },
                      {
                        onSuccess: () => {
                          toast.success(t('movements.returned'))
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
                          toast.error(apiErrorMessage(error, t('movements.returnFailed'))),
                      },
                    )
                  }
                >
                  {t('movements.returnIssue')}
                </Button>
              )}
            </td>
          </tr>
        )}
      />
    </>
  )
}
