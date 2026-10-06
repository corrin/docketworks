import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  consumeStockMutation,
  jobCostLinesDeleteDestroyMutation,
  jobCostLinesPartialUpdateMutation,
  jobJobsCostSetsCostLinesCreateMutation,
  jobJobsCostSetsRetrieveOptions,
  jobJobsCostSetsRetrieveQueryKey,
} from '@/api'
import type { CostLineCreateRequest, CostLineOut, CostLineUpdateRequest, CostSetOut } from '@/api'
import { costLineDisplay } from '@/features/shared/costLineDisplay'
import { useOptimisticRows } from '@/features/shared/optimistic'

import { invalidateJobViews } from '../invalidateJobViews'
import type { CostSetKind } from './types'

interface CreateLineCallbacks {
  onCreated: (line: CostLineOut) => void
  onFailed: () => void
}

/**
 * All server state for one cost set, in the TanStack Query cache and nowhere
 * else, written through the shared optimistic runner (serialized per cost
 * set, rollback on refusal, every failure toasts). Cost-line CRUD
 * deliberately carries no If-Match — per-line last-write-wins matched v1 and
 * per-line concurrency would be a new wire contract on both sides.
 */
export function useCostLines(jobId: string, kind: CostSetKind) {
  const queryClient = useQueryClient()
  const path = { job_id: jobId, kind }
  const queryKey = jobJobsCostSetsRetrieveQueryKey({ path })

  const grid = useOptimisticRows<CostSetOut, CostLineOut>({
    queryKey,
    rows: (costSet) => costSet.cost_lines,
    withRows: (costSet, cost_lines) => ({ ...costSet, cost_lines }),
    scopeId: `cost-set:${jobId}:${kind}`,
    // The cost set, plus the job's two views.
    //
    // The job detail is not refetched for anything it displays: it is refetched
    // for the ETag its 200/304 carries (apps/job/api.py get_full_job). Every
    // CostLine save and delete runs _update_cost_set_summary, which calls
    // touch_updated_at on the job (apps/job/models/costing.py), and the job's
    // ETag is generated from that updated_at — while the cost-line endpoints
    // never call _set_job_etag on their own responses. So a cost-line write
    // silently invalidates the ETag the concurrency interceptor holds, and only
    // a getFullJob refetch re-arms it; without one, the user's next header
    // inline edit sends a stale If-Match and 412s.
    // The timeline key travels with it because the same write is a
    // costline_created or costline_updated entry on the History tab.
    invalidate: () => {
      void queryClient.invalidateQueries({ queryKey })
      void invalidateJobViews(queryClient, jobId)
    },
  })

  const costSetQuery = useQuery({
    ...jobJobsCostSetsRetrieveOptions({ path }),
    enabled: grid.canRefetch,
  })
  const patchMutation = useMutation(grid.serialized(jobCostLinesPartialUpdateMutation()))
  const createMutation = useMutation(grid.serialized(jobJobsCostSetsCostLinesCreateMutation()))
  const deleteMutation = useMutation(grid.serialized(jobCostLinesDeleteDestroyMutation()))
  const consumeMutation = useMutation(grid.serialized(consumeStockMutation()))

  const patchLine = (lineId: string, body: CostLineUpdateRequest) =>
    grid.patchRow(
      lineId,
      costLineDisplay(body),
      () => patchMutation.mutateAsync({ path: { cost_line_id: lineId }, body }),
      'Failed to save the cost line',
    )

  const createLine = (body: CostLineCreateRequest, callbacks: CreateLineCallbacks) =>
    grid.appendRow(
      () => createMutation.mutateAsync({ path, body }),
      callbacks,
      'Failed to add the cost line',
    )

  /**
   * Book a material line by consuming stock (actual cost set only). The
   * SERVER creates the cost line — description, cost and markup-derived
   * revenue come from the stock row, so no unit_cost/unit_rev is sent.
   */
  const consumeStockLine = (stockId: string, quantity: string, callbacks: CreateLineCallbacks) =>
    grid.appendRow(
      () =>
        consumeMutation
          .mutateAsync({ path: { id: stockId }, body: { job_id: jobId, quantity } })
          .then((response) => response.line),
      callbacks,
      'Failed to consume the stock item',
    )

  const deleteLine = (lineId: string) =>
    grid.deleteRow(
      lineId,
      () => deleteMutation.mutateAsync({ path: { cost_line_id: lineId } }),
      'Failed to delete the cost line',
    )

  return { costSetQuery, patchLine, createLine, deleteLine, consumeStockLine }
}
