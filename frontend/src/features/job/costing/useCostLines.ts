import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  consumeStockMutation,
  jobCostLinesDeleteDestroyMutation,
  jobCostLinesPartialUpdateMutation,
  jobJobsCostSetsCostLinesCreateMutation,
  jobJobsCostSetsRetrieveOptions,
  jobJobsCostSetsRetrieveQueryKey,
} from '@/api'
import type { CostLineCreateRequest, CostLineOut, CostLineUpdateRequest, CostSetOut } from '@/api'
import type { CostSetKind } from './types'

interface CreateLineCallbacks {
  onCreated: (line: CostLineOut) => void
  onFailed: () => void
}

/**
 * All server state for one cost set, in the TanStack Query cache and nowhere
 * else. Writes are optimistic with rollback; every failure toasts (the E2E
 * console guard fails a spec on any console.error). Cost-line CRUD
 * deliberately carries no If-Match — per-line last-write-wins matched v1 and
 * per-line concurrency would be a new wire contract on both sides.
 *
 * After each settled write the cost set is invalidated: `summary` and the
 * per-line totals are server-owned (ADR 0046), so the refetch is what updates
 * them rather than local arithmetic.
 */
export function useCostLines(jobId: string, kind: CostSetKind) {
  const queryClient = useQueryClient()
  const path = { job_id: jobId, kind }
  const queryKey = jobJobsCostSetsRetrieveQueryKey({ path })
  const costSetQuery = useQuery(jobJobsCostSetsRetrieveOptions({ path }))

  const patchMutation = useMutation(jobCostLinesPartialUpdateMutation())
  const createMutation = useMutation(jobJobsCostSetsCostLinesCreateMutation())
  const deleteMutation = useMutation(jobCostLinesDeleteDestroyMutation())
  const consumeMutation = useMutation(consumeStockMutation())

  const invalidate = () => void queryClient.invalidateQueries({ queryKey })
  // An in-flight background refetch resolving AFTER an optimistic write
  // would clobber it with pre-write data; cancellation closes that window.
  const cancelInFlight = () => void queryClient.cancelQueries({ queryKey })

  const patchLine = (lineId: string, body: CostLineUpdateRequest) => {
    cancelInFlight()
    const snapshot = queryClient.getQueryData<CostSetOut>(queryKey)
    if (snapshot) {
      queryClient.setQueryData<CostSetOut>(
        queryKey,
        withLines(snapshot, (lines) =>
          lines.map((line) => (line.id === lineId ? applyPatchForDisplay(line, body) : line)),
        ),
      )
    }
    const snapshotLine = snapshot?.cost_lines.find((line) => line.id === lineId)
    patchMutation.mutate(
      { path: { cost_line_id: lineId }, body },
      {
        onSuccess: (updated) => {
          const current = queryClient.getQueryData<CostSetOut>(queryKey)
          if (current) {
            queryClient.setQueryData<CostSetOut>(
              queryKey,
              withLines(current, (lines) =>
                lines.map((line) =>
                  line.id === lineId ? mergeEchoFields(line, updated, body) : line,
                ),
              ),
            )
          }
        },
        onError: (error) => {
          // Per-field rollback against the CURRENT cache, not a wholesale
          // snapshot restore: two interleaved patches each roll back only
          // their own fields, so one failure cannot resurrect the other's
          // rejected values or revert its applied ones.
          const current = queryClient.getQueryData<CostSetOut>(queryKey)
          if (current && snapshotLine) {
            queryClient.setQueryData<CostSetOut>(
              queryKey,
              withLines(current, (lines) =>
                lines.map((line) =>
                  line.id === lineId ? revertPatchFields(line, snapshotLine, body) : line,
                ),
              ),
            )
          }
          toast.error(apiErrorMessage(error, 'Failed to save the cost line'))
        },
        onSettled: invalidate,
      },
    )
  }

  const createLine = (
    body: CostLineCreateRequest,
    { onCreated, onFailed }: CreateLineCallbacks,
  ) => {
    createMutation.mutate(
      { path, body },
      {
        onSuccess: (created) => {
          const current = queryClient.getQueryData<CostSetOut>(queryKey)
          if (current) {
            queryClient.setQueryData<CostSetOut>(
              queryKey,
              withLines(current, (lines) => [...lines, created]),
            )
          }
          onCreated(created)
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to add the cost line'))
          onFailed()
        },
        onSettled: invalidate,
      },
    )
  }

  /**
   * Book a material line by consuming stock (actual cost set only). The
   * SERVER creates the cost line — description, cost and markup-derived
   * revenue come from the stock row, so no unit_cost/unit_rev is sent.
   */
  const consumeStockLine = (
    stockId: string,
    quantity: string,
    { onCreated, onFailed }: CreateLineCallbacks,
  ) => {
    consumeMutation.mutate(
      { path: { id: stockId }, body: { job_id: jobId, quantity } },
      {
        onSuccess: (response) => {
          const current = queryClient.getQueryData<CostSetOut>(queryKey)
          if (current) {
            queryClient.setQueryData<CostSetOut>(
              queryKey,
              withLines(current, (lines) => [...lines, response.line]),
            )
          }
          onCreated(response.line)
        },
        onError: (error) => {
          toast.error(apiErrorMessage(error, 'Failed to consume the stock item'))
          onFailed()
        },
        onSettled: invalidate,
      },
    )
  }

  const deleteLine = (lineId: string) => {
    cancelInFlight()
    const snapshot = queryClient.getQueryData<CostSetOut>(queryKey)
    if (snapshot) {
      queryClient.setQueryData<CostSetOut>(
        queryKey,
        withLines(snapshot, (lines) => lines.filter((line) => line.id !== lineId)),
      )
    }
    deleteMutation.mutate(
      { path: { cost_line_id: lineId } },
      {
        onError: (error) => {
          // Re-insert only the deleted line into the CURRENT cache: a
          // wholesale snapshot restore would resurrect other lines' rejected
          // optimistic values — the failure the per-field patch rollback
          // exists to prevent.
          const current = queryClient.getQueryData<CostSetOut>(queryKey)
          if (current && snapshot) {
            queryClient.setQueryData<CostSetOut>(
              queryKey,
              withLines(current, (lines) => restoreDeletedLine(lines, snapshot.cost_lines, lineId)),
            )
          }
          toast.error(apiErrorMessage(error, 'Failed to delete the cost line'))
        },
        onSettled: invalidate,
      },
    )
  }

  return { costSetQuery, patchLine, createLine, deleteLine, consumeStockLine }
}

function withLines(costSet: CostSetOut, map: (lines: CostLineOut[]) => CostLineOut[]): CostSetOut {
  return { ...costSet, cost_lines: map(costSet.cost_lines) }
}

/**
 * Optimistic display value for a patched line. The wire accepts number|string
 * for decimals while CostLineOut carries strings; the server echo (onSuccess)
 * and the settle refetch replace this approximation with canonical values.
 */
function applyPatchForDisplay(line: CostLineOut, body: CostLineUpdateRequest): CostLineOut {
  const next: CostLineOut = { ...line }
  if (body.desc !== undefined) next.desc = body.desc
  if (body.kind !== undefined) next.kind = body.kind
  if (body.labour_subtype !== undefined) next.labour_subtype = body.labour_subtype
  if (body.quantity !== undefined) next.quantity = String(body.quantity)
  if (body.unit_cost !== undefined) next.unit_cost = String(body.unit_cost)
  if (body.unit_rev !== undefined) next.unit_rev = String(body.unit_rev)
  if (body.ext_refs !== undefined) next.ext_refs = body.ext_refs
  return next
}

/**
 * Apply from the echo only the fields the patch sent, plus the
 * server-computed line totals and timestamp — so one PATCH's echo cannot
 * clobber a later interleaved optimistic patch on the same line.
 */
export function mergeEchoFields(
  line: CostLineOut,
  echo: CostLineOut,
  body: CostLineUpdateRequest,
): CostLineOut {
  const next: CostLineOut = {
    ...line,
    total_cost: echo.total_cost,
    total_rev: echo.total_rev,
    updated_at: echo.updated_at,
  }
  if (body.desc !== undefined) next.desc = echo.desc
  if (body.kind !== undefined) next.kind = echo.kind
  if (body.labour_subtype !== undefined) next.labour_subtype = echo.labour_subtype
  if (body.quantity !== undefined) next.quantity = echo.quantity
  if (body.unit_cost !== undefined) next.unit_cost = echo.unit_cost
  if (body.unit_rev !== undefined) next.unit_rev = echo.unit_rev
  if (body.ext_refs !== undefined) next.ext_refs = echo.ext_refs
  return next
}

/** Put a failed delete's line back at its snapshot index, touching nothing else. */
export function restoreDeletedLine(
  current: CostLineOut[],
  snapshotLines: CostLineOut[],
  lineId: string,
): CostLineOut[] {
  const index = snapshotLines.findIndex((line) => line.id === lineId)
  const deleted = index === -1 ? undefined : snapshotLines[index]
  if (!deleted || current.some((line) => line.id === lineId)) return current
  const next = [...current]
  next.splice(Math.min(index, next.length), 0, deleted)
  return next
}

/** Undo exactly the fields a rejected patch touched, from the pre-patch line. */
function revertPatchFields(
  line: CostLineOut,
  snapshotLine: CostLineOut,
  body: CostLineUpdateRequest,
): CostLineOut {
  const next: CostLineOut = { ...line }
  if (body.desc !== undefined) next.desc = snapshotLine.desc
  if (body.kind !== undefined) next.kind = snapshotLine.kind
  if (body.labour_subtype !== undefined) next.labour_subtype = snapshotLine.labour_subtype
  if (body.quantity !== undefined) next.quantity = snapshotLine.quantity
  if (body.unit_cost !== undefined) next.unit_cost = snapshotLine.unit_cost
  if (body.unit_rev !== undefined) next.unit_rev = snapshotLine.unit_rev
  if (body.ext_refs !== undefined) next.ext_refs = snapshotLine.ext_refs
  return next
}
