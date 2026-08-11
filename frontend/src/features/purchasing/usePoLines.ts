import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  purchasingPurchaseOrdersPartialUpdateMutation,
  retrievePurchaseOrderOptions,
  retrievePurchaseOrderQueryKey,
} from '@/api'
import type {
  PurchaseOrderDetail,
  PurchaseOrderLineOut,
  PurchaseOrderLineUpdateRequest,
  PurchaseOrderUpdateRequest,
} from '@/api'
import { isConcurrencyError } from '@/lib/concurrency/interceptors'
import { draftCreateBody, type PoLineDraft } from './lines'

export type PoHeaderPatch = Pick<
  PurchaseOrderUpdateRequest,
  'reference' | 'status' | 'expected_delivery'
>

export type PoLinePatch = Omit<PurchaseOrderLineUpdateRequest, 'id'>

interface CreateLineCallbacks {
  onCreated: () => void
  onFailed: () => void
}

/**
 * All server state for one purchase order, in the TanStack Query cache and
 * nowhere else. Every write goes through the single PATCH endpoint (header
 * fields and a `lines` upsert array) under If-Match concurrency — the
 * interceptor attaches the ETag captured from the detail GET and toasts
 * 412/428 itself, so only non-concurrency failures toast here.
 *
 * The PATCH response carries no line echo (only `{id, status}` plus a fresh
 * ETag header), so the invalidate-refetch is what delivers server line ids
 * and canonical decimals — optimistic cache writes are display-only and the
 * refetch heals any rollback drift, which is why line rollbacks restore the
 * whole snapshot line rather than per-field (the per-field machinery in
 * useCostLines exists for interleaved patches that never refetch).
 */
export function usePoLines(poId: string) {
  const queryClient = useQueryClient()
  const path = { po_id: poId }
  const queryKey = retrievePurchaseOrderQueryKey({ path })
  const poQuery = useQuery(retrievePurchaseOrderOptions({ path }))
  const patchMutation = useMutation(purchasingPurchaseOrdersPartialUpdateMutation())

  const invalidate = () => queryClient.invalidateQueries({ queryKey })
  // An in-flight background refetch resolving AFTER an optimistic write
  // would clobber it with pre-write data; cancellation closes that window.
  const cancelInFlight = () => void queryClient.cancelQueries({ queryKey })

  const patchHeader = (fields: PoHeaderPatch) => {
    cancelInFlight()
    const snapshot = queryClient.getQueryData<PurchaseOrderDetail>(queryKey)
    if (snapshot) {
      queryClient.setQueryData<PurchaseOrderDetail>(queryKey, { ...snapshot, ...fields })
    }
    patchMutation.mutate(
      { path, body: fields },
      {
        onError: (error) => {
          const current = queryClient.getQueryData<PurchaseOrderDetail>(queryKey)
          if (current && snapshot) {
            queryClient.setQueryData<PurchaseOrderDetail>(queryKey, {
              ...current,
              ...headerFieldsFrom(snapshot, fields),
            })
          }
          if (!isConcurrencyError(error)) {
            toast.error(apiErrorMessage(error, 'Failed to save the purchase order.'))
          }
        },
        onSettled: () => void invalidate(),
      },
    )
  }

  const patchLine = (
    lineId: string,
    body: PoLinePatch,
    display?: Partial<PurchaseOrderLineOut>,
  ) => {
    cancelInFlight()
    const snapshot = queryClient.getQueryData<PurchaseOrderDetail>(queryKey)
    if (snapshot) {
      queryClient.setQueryData<PurchaseOrderDetail>(
        queryKey,
        withLines(snapshot, (lines) =>
          lines.map((line) => (line.id === lineId ? { ...line, ...display } : line)),
        ),
      )
    }
    const snapshotLine = snapshot?.lines.find((line) => line.id === lineId)
    patchMutation.mutate(
      { path, body: { lines: [{ id: lineId, ...body }] } },
      {
        onError: (error) => {
          const current = queryClient.getQueryData<PurchaseOrderDetail>(queryKey)
          if (current && snapshotLine) {
            queryClient.setQueryData<PurchaseOrderDetail>(
              queryKey,
              withLines(current, (lines) =>
                lines.map((line) => (line.id === lineId ? snapshotLine : line)),
              ),
            )
          }
          if (!isConcurrencyError(error)) {
            toast.error(apiErrorMessage(error, 'Failed to save the purchase order line.'))
          }
        },
        onSettled: () => void invalidate(),
      },
    )
  }

  const createLine = (draft: PoLineDraft, { onCreated, onFailed }: CreateLineCallbacks) => {
    patchMutation.mutate(
      { path, body: { lines: [draftCreateBody(draft)] } },
      {
        onSuccess: () => {
          // The refetch must land before the draft row is removed: the PATCH
          // echoes no line, so removing the draft on the 200 alone would blank
          // the row until the detail query caught up.
          void invalidate().then(onCreated)
        },
        onError: (error) => {
          if (!isConcurrencyError(error)) {
            toast.error(apiErrorMessage(error, 'Failed to add the purchase order line.'))
          }
          onFailed()
        },
      },
    )
  }

  return { poQuery, patchHeader, patchLine, createLine }
}

function withLines(
  po: PurchaseOrderDetail,
  map: (lines: PurchaseOrderLineOut[]) => PurchaseOrderLineOut[],
): PurchaseOrderDetail {
  return { ...po, lines: map(po.lines) }
}

/** The snapshot's values for exactly the header fields a rejected patch sent. */
function headerFieldsFrom(
  snapshot: PurchaseOrderDetail,
  fields: PoHeaderPatch,
): Partial<PurchaseOrderDetail> {
  const restored: Partial<PurchaseOrderDetail> = {}
  if (fields.reference !== undefined) restored.reference = snapshot.reference
  if (fields.status !== undefined) restored.status = snapshot.status
  if (fields.expected_delivery !== undefined)
    restored.expected_delivery = snapshot.expected_delivery
  return restored
}
