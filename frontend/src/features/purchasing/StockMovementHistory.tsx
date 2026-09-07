import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { toast } from 'sonner'
import {
  apiErrorMessage,
  costLineStockMovementRetrieveOptions,
  stockMovementsListOptions,
  stocktakeMovementsListOptions,
  stockMovementReturnMutation,
  type StockMovementOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { ListTable } from '@/features/shared/ListTable'
import { formatDateTime } from '@/lib/format'

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
  const history = useQuery(stockMovementsListOptions({ path: { id: stockId } }))
  return (
    <MovementRows
      rows={history.data}
      pending={history.isPending}
      failed={history.isError}
      retry={() => void history.refetch()}
    />
  )
}
export function StocktakeMovementHistory({ countId }: { countId: string }) {
  const history = useQuery(stocktakeMovementsListOptions({ path: { id: countId } }))
  return (
    <MovementRows
      rows={history.data}
      pending={history.isPending}
      failed={history.isError}
      retry={() => void history.refetch()}
    />
  )
}
function MovementRows({
  rows,
  pending,
  failed,
  retry,
}: {
  rows: StockMovementOut[] | undefined
  pending: boolean
  failed: boolean
  retry: () => void
}) {
  const cache = useQueryClient()
  const reverse = useMutation(stockMovementReturnMutation())
  return (
    <ListTable
      isPending={pending}
      isError={failed}
      onRetry={retry}
      rows={rows}
      loadingLabel="Loading movements…"
      errorLabel="Unable to load stock history."
      emptyLabel="No movements recorded."
      wrapperClassName="max-h-[55vh]"
      head={
        <tr>
          <th className="p-2 text-left">Recorded</th>
          <th className="p-2 text-left">Item</th>
          <th className="p-2">Before → after</th>
          <th className="p-2 text-left">Counterpart</th>
          <th className="p-2 text-left">Reason / operator</th>
          <th className="p-2">Action</th>
        </tr>
      }
      renderRow={(movement) => (
        <tr key={movement.id} className="border-b">
          <td className="p-2">{formatDateTime(movement.recorded_at)}</td>
          <td className="p-2">{movement.description}</td>
          <td className="p-2">
            {movement.quantity_before} → {movement.quantity_after}
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
                        void cache.invalidateQueries()
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
  )
}
