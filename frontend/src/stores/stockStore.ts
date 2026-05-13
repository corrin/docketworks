import { defineStore } from 'pinia'
import { ref } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { normalizeOptionalDecimal } from '@/utils/number'
import { dataFreshness } from '@/composables/useDataFreshness'
import { createDatasetCache } from '@/composables/useDatasetCache'

const stockArraySchema = z.array(schemas.StockItem)

export type StockItem = z.infer<typeof schemas.StockItem>
type StockConsumeRequest = z.infer<typeof schemas.StockConsumeRequest>
type StockConsumeResponse = z.infer<typeof schemas.StockConsumeResponse>
type StockCreateRequest = z.infer<typeof schemas.StockItemRequest>

// Narrow Zodios error shape where response is available at error.cause.received
type ZodiosErrorWithReceived = { cause?: { received?: unknown } }
function hasReceivedPayload(err: unknown): err is ZodiosErrorWithReceived {
  if (!err || typeof err !== 'object') return false
  const cause = (err as Record<string, unknown>).cause
  if (!cause || typeof cause !== 'object') return false
  return 'received' in cause
}

export const useStockStore = defineStore('stock', () => {
  const items = ref<StockItem[]>([])
  const loading = ref(false)
  type StockFetchOptions = { signal?: AbortSignal; timeout?: number; force?: boolean }

  const stockCache = createDatasetCache<'all', StockItem[]>({
    getCached: () => items.value,
    hasCached: () => items.value.length > 0,
    onResolved: (_key, value) => {
      items.value = value
    },
    onInvalidate: () => {
      items.value = []
    },
  })

  // When the backend's `stock` dataset version changes, drop the cache so the
  // next fetchStock() / fetchStockSafe() call refetches fresh prices. The
  // freshness mechanism is what makes the cache safe to hold long-term — without
  // this subscription, a session-long picker would autofill stale unit costs.
  dataFreshness.subscribe('stock', () => {
    stockCache.invalidate()
  })

  async function loadStock({
    signal,
    timeout,
  }: {
    signal?: AbortSignal
    timeout?: number
  }): Promise<StockItem[]> {
    try {
      const response = await api.purchasing_stock_list({ signal, timeout })
      return response || []
    } catch (error: unknown) {
      if (hasReceivedPayload(error)) {
        try {
          const receivedData = error.cause?.received
          if (Array.isArray(receivedData)) {
            return stockArraySchema.parse(receivedData)
          }
        } catch (parseError) {
          console.error('Error parsing stock data:', parseError)
        }
      }
      throw error
    }
  }

  async function fetchStock(force = false): Promise<StockItem[]> {
    if (!force && items.value.length > 0) {
      return items.value
    }

    loading.value = true
    try {
      return await stockCache.getOrLoad('all', () => loadStock({}), { force })
    } finally {
      loading.value = false
    }
  }

  // Non-blocking, abortable, one-shot fetch suitable for background refreshes
  function fetchStockSafe(options: StockFetchOptions = {}): Promise<StockItem[] | void> {
    const { signal, timeout, force = false } = options

    if (!force && items.value.length > 0) {
      return Promise.resolve(items.value)
    }

    loading.value = true
    return stockCache
      .getOrLoad('all', () => loadStock({ signal, timeout }), { force })
      .catch((error) => {
        console.warn('fetchStockSafe: background stock fetch failed (non-blocking):', error)
      })
      .finally(() => {
        loading.value = false
      })
  }

  async function consumeStock(
    id: string,
    payload: {
      job_id: string
      quantity: number
      unit_cost?: number | string | null
      unit_rev?: number | string | null
    },
  ): Promise<StockConsumeResponse> {
    const normalizedUnitCost = normalizeOptionalDecimal(payload.unit_cost, {
      decimalPlaces: 2,
    })
    const normalizedUnitRev = normalizeOptionalDecimal(payload.unit_rev, {
      decimalPlaces: 2,
    })

    const consumePayload: StockConsumeRequest = {
      job_id: payload.job_id,
      quantity: payload.quantity,
      ...(normalizedUnitCost !== undefined ? { unit_cost: normalizedUnitCost } : {}),
      ...(normalizedUnitRev !== undefined ? { unit_rev: normalizedUnitRev } : {}),
    }
    return await api.consumeStock(consumePayload, {
      params: { id },
    })
  }

  async function create(payload: StockCreateRequest) {
    const response = await api.purchasing_stock_create(payload)
    return response
  }

  async function deactivate(id: string) {
    await api.purchasing_stock_destroy(undefined, { params: { id } })
  }

  return { items, loading, fetchStock, fetchStockSafe, consumeStock, create, deactivate }
})
