import { useState } from 'react'
import { useMutation, useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  purchasingStockListOptions,
  stocktakeListOptions,
  stocktakeRetrieveOptions,
  purchasingStockSearchRetrieveOptions,
  stocktakeUpdateMutation,
  stocktakePostMutation,
  stocktakeCorrectMutation,
  type StocktakeDetail,
  type StocktakeLineWrite,
  type StockItem,
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
  const { t } = useTranslation('purchasing')
  const count = useQuery(stocktakeRetrieveOptions({ path: { id: stocktakeId } }))
  return (
    <QueryState
      isPending={count.isPending}
      isError={count.isError && count.data === undefined}
      onRetry={() => void count.refetch()}
      loadingLabel={t('stocktakeDetail.loading')}
      errorLabel={t('stocktakeDetail.loadFailed')}
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
  const { t } = useTranslation('purchasing')
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
      purchasingStockSearchRetrieveOptions({
        query: { stock_ids, page_size: 100, include_inactive: true },
      }),
    ),
  })
  const current = new Map(
    observations.flatMap((query) =>
      query.data === undefined ? [] : query.data.results.map((stock) => [stock.id, stock] as const),
    ),
  )
  const refreshStock = async () => {
    await Promise.all(observations.map((query) => query.refetch({ throwOnError: true })))
    // Posting moves balances and closes the draft; the list and the stock page
    // hold both for staleTime unless told, so a user clicking straight through
    // to them saw Draft and pre-post balances for thirty seconds.
    await Promise.all([
      cache.invalidateQueries({ queryKey: stocktakeListOptions().queryKey }),
      cache.invalidateQueries({ queryKey: purchasingStockListOptions().queryKey }),
    ])
  }
  const failed = async (error: unknown) => {
    if (isConcurrencyError(error)) setConflicted(true)
    try {
      await Promise.all([refresh(), refreshStock()])
    } catch {
      toast.error(t('stocktakeDetail.refreshFailed'))
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
      toast.error(t('stocktakeDetail.reloadFailed'))
    } finally {
      setReloading(false)
    }
  }
  const changed = (next: CountRow[]) => {
    setRows(next)
    setDirty(true)
  }
  const accepted = (saved: StocktakeDetail) => {
    // The response we were handed is authoritative, and the version comes from
    // the shared ETag store, so nothing may refetch this stocktake behind us: a
    // GET issued before this write and landing after it puts the older revision
    // back, and the next save then fails a precondition nobody violated. That is
    // why the write seeds the cache instead of invalidating it. Stock balances
    // move only when a count is posted, and refreshStock owns that.
    cache.setQueryData(stocktakeRetrieveOptions({ path: { id: saved.id } }).queryKey, saved)
    setVersion(snapshotEtag(saved.id))
    setRows(draftRows(saved))
    setDirty(false)
  }
  const save = () => {
    if (rows.some((row) => row.unitCostInput === '')) {
      toast.error(t('stocktakeDetail.unitCostRequired'))
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
          toast.success(t('stocktakeDetail.draftSaved'))
        },
        onError: failed,
      },
    )
  }
  const addStock = (stock: StockItem) =>
    changed([
      ...rows,
      {
        id: crypto.randomUUID(),
        stock_id: stock.id,
        description: stock.description,
        location: stock.location,
        expected_quantity: Number(stock.quantity),
        expected_version: stock.inventory_version,
        counted_quantity: null,
        unit_cost: Number(stock.unit_cost),
        reason: null,
        unitCostInput: stock.unit_cost,
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
            {t('stocktakeDetail.backToList')}
          </Link>
          <h1 className="text-xl font-bold">
            {t('stocktakeDetail.title', { date: formatDateTime(count.created_at) })}
          </h1>
          <p>
            {t('stocktakeDetail.stateAndAuthor', {
              state: readOnly
                ? t('stocktakeDetail.posted')
                : dirty
                  ? t('stocktakeDetail.unsaved')
                  : t('stocktakeDetail.draft'),
              author: count.author,
            })}
          </p>
        </div>
        <Link
          className="text-blue-700 underline"
          to="/jobs/$jobId"
          params={{ jobId: count.adjustment_job_id }}
          title={t('stocktakeDetail.adjustmentJobTitle')}
        >
          {t('stocktakeDetail.adjustmentJob')}
        </Link>
      </div>
      {count.corrects_id && (
        <Link
          className="text-blue-700 underline"
          to="/purchasing/stocktakes/$stocktakeId"
          params={{ stocktakeId: count.corrects_id }}
          title={t('stocktakeDetail.originalTitle')}
        >
          {t('stocktakeDetail.original')}
        </Link>
      )}
      <p>{t('stocktakeDetail.instructions')}</p>
      <EntryGridSection
        title={t('stocktakeDetail.physicalCount')}
        actions={
          !readOnly && (
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={busy}
                title={showPicker ? undefined : t('stocktakeDetail.showPickerTitle')}
                onClick={() => setShowPicker(!showPicker)}
              >
                {showPicker ? t('stocktakeDetail.hidePicker') : t('stocktakeDetail.showPicker')}
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                title={t('stocktakeDetail.addFoundTitle')}
                onClick={addFound}
              >
                {t('stocktakeDetail.addFound')}
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
                      expected_quantity: Number(latest.quantity),
                      expected_version: latest.inventory_version,
                      unit_cost: Number(latest.unit_cost),
                      unitCostInput: latest.unit_cost,
                      counted_quantity: null,
                      countInput: '',
                    }
                  : row,
              ),
            )
          }}
        />
        <p className="mt-3" title={t('stocktakeDetail.progressTitle')}>
          {t('stocktakeDetail.progress', {
            items: rows.length,
            counted: rows.filter((row) => row.counted_quantity !== null).length,
          })}
        </p>
      </EntryGridSection>
      {conflicted && (
        <div role="alert">
          <p>{t('stocktakeDetail.conflict')}</p>
          <Button variant="outline" disabled={reloading} onClick={() => void reloadSaved()}>
            {t('stocktakeDetail.reloadSaved')}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-red-700">
          {apiErrorMessage(error, t('stocktakeDetail.saveFailed'))}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        {!readOnly && (
          <>
            <Button
              variant="outline"
              disabled={busy || !dirty}
              title={t('stocktakeDetail.saveDraftTitle')}
              onClick={save}
            >
              {t('stocktakeDetail.saveDraft')}
            </Button>
            <Button
              disabled={busy || dirty || !rows.some((row) => row.counted_quantity !== null)}
              title={t('stocktakeDetail.postTitle')}
              onClick={() =>
                post.mutate(
                  { path: { id: count.id }, headers: { 'If-Match': version } },
                  {
                    onSuccess: (saved) => {
                      accepted(saved)
                      void refreshStock().catch(() =>
                        toast.error(t('stocktakeDetail.postedRefreshFailed')),
                      )
                      toast.success(t('stocktakeDetail.stocktakePosted'))
                    },
                    onError: failed,
                  },
                )
              }
            >
              {t('stocktakeDetail.post')}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              title={t('stocktakeDetail.checkStockTitle')}
              onClick={() =>
                void refreshStock().catch(() =>
                  toast.error(t('stocktakeDetail.stockRefreshFailed')),
                )
              }
            >
              {t('stocktakeDetail.checkStock')}
            </Button>
          </>
        )}
        {readOnly && (
          <Button
            disabled={busy}
            title={t('stocktakeDetail.createCorrectionTitle')}
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
            {t('stocktakeDetail.createCorrection')}
          </Button>
        )}
      </div>
      {readOnly && (
        <EntryGridSection title={t('stocktakeDetail.postedMovements')}>
          <StocktakeMovementHistory countId={count.id} />
        </EntryGridSection>
      )}
      {count.posted_at !== null && (
        <p>{t('stocktakeDetail.postedNote', { date: formatDateTime(count.posted_at) })}</p>
      )}
    </div>
  )
}
