import { useState } from 'react'
import { useMutation, useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  stocktakeRetrieveOptions,
  stocktakeStockListOptions,
  stocktakeUpdateMutation,
  stocktakePostMutation,
  stocktakeCorrectMutation,
  type StocktakeDetail,
  type StocktakeLineWrite,
  type StocktakeStockOut,
} from '@/api'
import { getEtag, etagKey } from '@/lib/concurrency/etag-store'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { Button } from '@/components/ui/button'
import { EntryGridSection } from '@/features/shared/EntryGridSection'
import { QueryState } from '@/features/shared/QueryState'
import { formatDateTime } from '@/lib/format'
import { StocktakeMovementHistory } from './StockMovementHistory'
import { StocktakeGrid, type CountRow } from './StocktakeGrid'
import { StocktakeStockPicker } from './StocktakeStockPicker'

function draftRows(count: StocktakeDetail): CountRow[] {
  return count.lines.map((line) => ({
    ...line,
    unitCostInput: String(line.unit_cost),
    countInput: line.counted_quantity === null ? '' : String(line.counted_quantity),
  }))
}
export function StocktakeDetailPage({ stocktakeId }: { stocktakeId: string }) {
  const count = useQuery(stocktakeRetrieveOptions({ path: { id: stocktakeId } }))
  return (
    <QueryState
      isPending={count.isPending}
      isError={count.isError && count.data === undefined}
      onRetry={() => void count.refetch()}
      loadingLabel="Loading count…"
      errorLabel="Unable to load count."
    >
      {count.data && (
        <StocktakeEditor
          key={stocktakeId}
          count={count.data}
          refresh={async () => {
            const fresh = await count.refetch({ throwOnError: true })
            if (fresh.data === undefined) throw new Error('Stocktake reload returned no data')
            return fresh.data
          }}
        />
      )}
    </QueryState>
  )
}
function snapshotEtag(id: string): string {
  const etag = getEtag(etagKey('stocktake', id))
  if (etag === null) throw new Error('Stocktake response is missing its ETag')
  return etag
}
function StocktakeEditor({
  count,
  refresh,
}: {
  count: StocktakeDetail
  refresh: () => Promise<StocktakeDetail>
}) {
  const navigate = useNavigate()
  const cache = useQueryClient()
  const [rows, setRows] = useState(() => draftRows(count))
  const [version, setVersion] = useState(() => snapshotEtag(count.id))
  const [reloading, setReloading] = useState(false)
  const [conflicted, setConflicted] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [showPicker, setShowPicker] = useState(false)
  const update = useMutation(stocktakeUpdateMutation())
  const post = useMutation(stocktakePostMutation())
  const correct = useMutation(stocktakeCorrectMutation())
  const readOnly = count.posted_at !== null
  const busy = reloading || conflicted || update.isPending || post.isPending || correct.isPending
  const stockIds = rows.flatMap((row) => (row.stock_id === null ? [] : [row.stock_id]))
  const batches: string[][] = []
  for (let offset = 0; offset < stockIds.length; offset += 100)
    batches.push(stockIds.slice(offset, offset + 100))
  const observations = useQueries({
    queries: batches.map((stock_ids) =>
      stocktakeStockListOptions({ query: { stock_ids, page_size: 100 } }),
    ),
  })
  const current = new Map(
    observations.flatMap((query) =>
      query.data === undefined ? [] : query.data.results.map((stock) => [stock.id, stock] as const),
    ),
  )
  const refreshStock = async () => {
    await Promise.all(observations.map((query) => query.refetch({ throwOnError: true })))
  }
  const failed = async (error: unknown) => {
    if (isConcurrencyError(error)) setConflicted(true)
    try {
      await Promise.all([refresh(), refreshStock()])
    } catch {
      toast.error('Unable to refresh. Your entries have been retained.')
    }
  }
  const reloadSaved = async () => {
    setReloading(true)
    try {
      const saved = await refresh()
      accepted(saved)
      setConflicted(false)
      update.reset()
      post.reset()
    } catch {
      toast.error('Unable to reload. Your entries have been retained.')
    } finally {
      setReloading(false)
    }
  }
  const changed = (next: CountRow[]) => {
    setRows(next)
    setDirty(true)
  }
  const accepted = (saved: StocktakeDetail) => {
    setVersion(snapshotEtag(saved.id))
    setRows(draftRows(saved))
    setDirty(false)
    cache.setQueryData(stocktakeRetrieveOptions({ path: { id: saved.id } }).queryKey, saved)
    void cache.invalidateQueries()
  }
  const save = () => {
    if (rows.some((row) => row.unitCostInput === '')) {
      toast.error('Enter a unit cost for every found item.')
      return
    }
    const lines: StocktakeLineWrite[] = rows.map((row) => ({
      id: row.id,
      stock_id: row.stock_id,
      description: row.description,
      location: row.location,
      expected_quantity: row.expected_quantity,
      expected_version: row.expected_version,
      counted_quantity: row.counted_quantity,
      unit_cost: row.unit_cost,
      reason: row.reason,
    }))
    update.mutate(
      { path: { id: count.id }, body: { lines }, headers: { 'If-Match': version } },
      {
        onSuccess: (saved) => {
          accepted(saved)
          toast.success('Draft saved')
        },
        onError: failed,
      },
    )
  }
  const addStock = (stock: StocktakeStockOut) =>
    changed([
      ...rows,
      {
        id: crypto.randomUUID(),
        stock_id: stock.id,
        description: stock.description,
        location: stock.location,
        expected_quantity: stock.quantity,
        expected_version: stock.inventory_version,
        counted_quantity: null,
        unit_cost: stock.unit_cost,
        reason: null,
        unitCostInput: String(stock.unit_cost),
        countInput: '',
      },
    ])
  const addFound = () =>
    changed([
      ...rows,
      {
        id: crypto.randomUUID(),
        stock_id: null,
        description: '',
        location: null,
        expected_quantity: 0,
        expected_version: 0,
        counted_quantity: null,
        unit_cost: 0,
        reason: 'Unexplained surplus',
        unitCostInput: '',
        countInput: '',
      },
    ])
  const error = update.error ?? post.error ?? correct.error
  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link className="text-blue-700 underline" to="/purchasing/stocktakes">
            Stocktakes
          </Link>
          <h1 className="text-xl font-bold">Stocktake · {formatDateTime(count.created_at)}</h1>
          <p>
            {readOnly ? 'Posted' : dirty ? 'Unsaved count' : 'Draft'} · {count.author}
          </p>
        </div>
        <Link
          className="text-blue-700 underline"
          to="/jobs/$jobId"
          params={{ jobId: count.adjustment_job_id }}
        >
          Stocktake Adjustments job
        </Link>
      </div>
      {count.corrects_id && (
        <Link
          className="text-blue-700 underline"
          to="/purchasing/stocktakes/$stocktakeId"
          params={{ stocktakeId: count.corrects_id }}
        >
          Original stocktake
        </Link>
      )}
      <p>
        Count unassigned workshop material. Leave uncounted items blank; enter zero when nothing is
        present.
      </p>
      <EntryGridSection
        title="Physical count"
        actions={
          !readOnly && (
            <div className="flex gap-2">
              <Button variant="outline" disabled={busy} onClick={() => setShowPicker(!showPicker)}>
                {showPicker ? 'Hide stock search' : 'Add stock to count'}
              </Button>
              <Button variant="outline" disabled={busy} onClick={addFound}>
                Add found item
              </Button>
            </div>
          )
        }
      >
        {showPicker && !readOnly && (
          <StocktakeStockPicker
            selected={new Set(rows.flatMap((row) => (row.stock_id === null ? [] : [row.stock_id])))}
            onSelect={addStock}
          />
        )}
        <StocktakeGrid
          rows={rows}
          readOnly={readOnly || busy}
          current={current}
          update={(id, patch) =>
            changed(rows.map((row) => (row.id === id ? { ...row, ...patch } : row)))
          }
          remove={(id) => changed(rows.filter((row) => row.id !== id))}
          recount={(id) => {
            const selectedRow = rows.find((item) => item.id === id)
            if (selectedRow === undefined || selectedRow.stock_id === null) return
            const latest = current.get(selectedRow.stock_id)
            if (!latest) return
            changed(
              rows.map((row) =>
                row.id === id
                  ? {
                      ...row,
                      expected_quantity: latest.quantity,
                      expected_version: latest.inventory_version,
                      unit_cost: latest.unit_cost,
                      unitCostInput: String(latest.unit_cost),
                      counted_quantity: null,
                      countInput: '',
                    }
                  : row,
              ),
            )
          }}
        />
        <p className="mt-3">
          {rows.length} items · {rows.filter((row) => row.counted_quantity !== null).length} counted
        </p>
      </EntryGridSection>
      {conflicted && (
        <div role="alert">
          <p>
            This draft was saved elsewhere. Reloading will replace your retained entries with the
            saved draft.
          </p>
          <Button variant="outline" disabled={reloading} onClick={() => void reloadSaved()}>
            Reload saved draft
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-red-700">
          {apiErrorMessage(error, 'Unable to save stocktake. Your entries have been retained.')}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        {!readOnly && (
          <>
            <Button variant="outline" disabled={busy || !dirty} onClick={save}>
              Save draft
            </Button>
            <Button
              disabled={busy || dirty || !rows.some((row) => row.counted_quantity !== null)}
              onClick={() =>
                post.mutate(
                  { path: { id: count.id }, headers: { 'If-Match': version } },
                  {
                    onSuccess: (saved) => {
                      accepted(saved)
                      toast.success('Stocktake posted')
                    },
                    onError: failed,
                  },
                )
              }
            >
              Post stocktake
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                void refreshStock().catch(() => toast.error('Unable to refresh current stock.'))
              }
            >
              Check current stock
            </Button>
          </>
        )}
        {readOnly && (
          <Button
            disabled={busy}
            onClick={() =>
              correct.mutate(
                { path: { id: count.id }, headers: { 'If-Match': version } },
                {
                  onSuccess: (draft) =>
                    void navigate({
                      to: '/purchasing/stocktakes/$stocktakeId',
                      params: { stocktakeId: draft.id },
                    }),
                },
              )
            }
          >
            Create correction
          </Button>
        )}
      </div>
      {readOnly && (
        <EntryGridSection title="Posted movements">
          <StocktakeMovementHistory countId={count.id} />
        </EntryGridSection>
      )}
      {count.posted_at !== null && (
        <p>
          Posted {formatDateTime(count.posted_at)}. Surplus moves from the adjustment job into
          workshop stock; shortages move the other way.
        </p>
      )}
    </div>
  )
}
