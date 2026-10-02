import { useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  purchasingPurchaseOrdersPartialUpdate,
  retrievePurchaseOrderOptions,
  retrievePurchaseOrderQueryKey,
} from '@/api'
import type {
  PurchaseOrderDetail,
  PurchaseOrderLineOut,
  PurchaseOrderLineUpdateRequest,
  PurchaseOrderUpdateRequest,
} from '@/api'
import { useOptimisticRows } from '@/features/shared/optimistic'
import { isConcurrencyError, type ConcurrencyError } from '@/lib/concurrency/interceptors'
import { draftCreateBody, type PoLineDraft } from './lines'

export type PoHeaderPatch = Pick<
  PurchaseOrderUpdateRequest,
  'reference' | 'status' | 'expected_delivery' | 'pickup_address_id'
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
 * final refetch reconciles the queue. Rollbacks restore only fields still
 * showing the rejected edit, preserving a later operator change.
 */
export function usePoLines(poId: string) {
  const queryClient = useQueryClient()
  const path = { po_id: poId }
  const queryKey = retrievePurchaseOrderQueryKey({ path })
  const poQuery = useQuery(retrievePurchaseOrderOptions({ path }))
  const mutationKey = ['purchase-order-write', poId]
  const blocked = useRef<ConcurrencyError | null>(null)
  const createdCallbacks = useRef<(() => void)[]>([])

  const grid = useOptimisticRows<PurchaseOrderDetail, PurchaseOrderLineOut>({
    queryKey,
    rows: (po) => po.lines,
    withRows: (po, lines) => ({ ...po, lines }),
    scopeId: `purchase-order:${poId}`,
    // GPT: A product response must not refetch over the queued TBC override.
    // Reconcile after the entire PO queue; retain created drafts until their
    // server IDs arrive.
    invalidate: async () => {
      if (queryClient.isMutating({ mutationKey }) !== 0) return
      await queryClient.invalidateQueries({ queryKey })
      for (const callback of createdCallbacks.current.splice(0)) callback()
    },
    beforeWrite: () => {
      if (queryClient.isMutating({ mutationKey }) === 0) blocked.current = null
    },
    // The interceptor toasts a 412/428 itself.
    shouldToast: (error) => !isConcurrencyError(error),
  })

  const patchMutation = useMutation({
    ...grid.serialized({ mutationKey }),
    mutationFn: async (options: Parameters<typeof purchasingPurchaseOrdersPartialUpdate>[0]) => {
      if (blocked.current !== null) throw blocked.current
      try {
        const response = await purchasingPurchaseOrdersPartialUpdate({
          ...options,
          throwOnError: true,
        })
        return response.data
      } catch (error) {
        // GPT: A 412 refetch may capture a newer ETag; queued edits must not silently rebase onto it.
        if (isConcurrencyError(error)) blocked.current = error
        throw error
      }
    },
  })

  // `display` is what the optimistic cache shows for a field the wire carries
  // by id only — the pickup address is nested on the read side and an id on
  // the write side, so the caller supplies the object it already has.
  const patchHeader = (fields: PoHeaderPatch, display?: Partial<PurchaseOrderDetail>) =>
    grid.patchDoc(
      { ...fields, ...display },
      () => patchMutation.mutateAsync({ path, body: fields }).then(() => undefined),
      'Failed to save the purchase order.',
    )

  const patchLine = (lineId: string, body: PoLinePatch, display?: Partial<PurchaseOrderLineOut>) =>
    grid.patchRow(
      lineId,
      display ?? {},
      () =>
        patchMutation
          .mutateAsync({ path, body: { lines: [{ id: lineId, ...body }] } })
          .then(() => undefined),
      'Failed to save the purchase order line.',
    )

  const createLine = (draft: PoLineDraft, { onCreated, onFailed }: CreateLineCallbacks) => {
    grid.beforeWrite()
    void patchMutation
      .mutateAsync({ path, body: { lines: [draftCreateBody(draft)] } })
      .then(
        () => {
          createdCallbacks.current.push(onCreated)
        },
        (error: unknown) => {
          if (!isConcurrencyError(error)) {
            toast.error(apiErrorMessage(error, 'Failed to add the purchase order line.'))
          }
          onFailed()
        },
      )
      .then(grid.invalidate)
  }

  const deleteLine = (lineId: string) =>
    grid.deleteRow(
      lineId,
      () => patchMutation.mutateAsync({ path, body: { lines_to_delete: [lineId] } }),
      'Failed to delete the purchase order line.',
    )

  return { poQuery, patchHeader, patchLine, createLine, deleteLine }
}
