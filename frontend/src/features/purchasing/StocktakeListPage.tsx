import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  stocktakeCreateMutation,
  stocktakeListOptions,
  stocktakeSetupCreateMutation,
  stocktakeSetupRetrieveOptions,
} from '@/api'
import { Button } from '@/components/ui/button'
import { ListTable } from '@/features/shared/ListTable'
import { QueryState } from '@/features/shared/QueryState'
import { formatCurrency, formatDateTime } from '@/lib/format'

const failure = (error: unknown) => toast.error(apiErrorMessage(error, 'Unable to save stocktake.'))

export function StocktakeListPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const list = useQuery(stocktakeListOptions({ query: { page } }))
  const setup = useQuery(stocktakeSetupRetrieveOptions())
  const configure = useMutation(stocktakeSetupCreateMutation())
  const create = useMutation(stocktakeCreateMutation())
  const configured = setup.data !== undefined && setup.data.adjustment_job_id !== null
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Stocktake</h1>
        <Button
          disabled={!configured || create.isPending}
          onClick={() =>
            create.mutate(
              { body: {} },
              {
                onSuccess: (count) =>
                  void navigate({
                    to: '/purchasing/stocktakes/$stocktakeId',
                    params: { stocktakeId: count.id },
                  }),
                onError: failure,
              },
            )
          }
        >
          New stocktake
        </Button>
      </div>
      <QueryState
        isPending={setup.isPending}
        isError={setup.isError}
        onRetry={() => void setup.refetch()}
        loadingLabel="Loading stocktake setup…"
        errorLabel="Unable to load stocktake setup."
      >
        {!configured && (
          <div className="space-y-3">
            <p>
              Create the ongoing, non-billable Stocktake Adjustments job to record found and missing
              material.
            </p>
            <Button
              disabled={configure.isPending}
              onClick={() =>
                configure.mutate(
                  {},
                  {
                    onSuccess: () => void setup.refetch(),
                    onError: failure,
                  },
                )
              }
            >
              Set up stocktake
            </Button>
          </div>
        )}
      </QueryState>
      <ListTable
        isPending={list.isPending}
        isError={list.isError}
        onRetry={() => void list.refetch()}
        loadingLabel="Loading counts…"
        errorLabel="Unable to load counts."
        emptyLabel="No stocktakes yet."
        rows={list.data?.results}
        wrapperClassName="max-h-[65vh]"
        head={
          <tr>
            <th className="p-3 text-left">Date</th>
            <th className="p-3 text-left">Counted by</th>
            <th className="p-3 text-left">Status</th>
            <th className="p-3 text-right">Stock value difference</th>
          </tr>
        }
        renderRow={(count) => (
          <tr key={count.id} className="border-b">
            <td className="p-3">
              <Link
                className="text-blue-700 underline"
                to="/purchasing/stocktakes/$stocktakeId"
                params={{ stocktakeId: count.id }}
              >
                {formatDateTime(count.created_at)}
              </Link>
            </td>
            <td className="p-3">{count.author}</td>
            <td className="p-3">{count.posted_at === null ? 'Draft' : 'Posted'}</td>
            <td className="p-3 text-right">{formatCurrency(count.discrepancy_value)}</td>
          </tr>
        )}
      />
      {list.data && (
        <div className="flex items-center gap-3">
          <span>{list.data.count} stocktakes</span>
          <Button variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span>Page {page}</span>
          <Button
            variant="outline"
            disabled={page * 50 >= list.data.count}
            onClick={() => setPage(page + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
