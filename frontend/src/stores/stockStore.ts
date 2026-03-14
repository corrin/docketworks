import { defineStore } from 'pinia'
import { ref } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'
import { normalizeOptionalDecimal } from '@/utils/number'

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
  let inFlight: Promise<StockItem[]> | null = null
  type StockFetchOptions = { signal?: AbortSignal; timeout?: number; force?: boolean }

  // Single internal fetch routine used by both public methods
  function startStockFetch({ signal, timeout }: { signal?: AbortSignal; timeout?: number }) {
    return (async () => {
      try {
        // Use the list endpoint to fetch all active stock items
        const response = await api.purchasing_rest_stock_list({ signal, timeout })
        items.value = response || []
        return items.value
      } catch (error: unknown) {
        // Handle zodios validation error and extract the actual data
        if (hasReceivedPayload(error)) {
          try {
            const receivedData = error.cause?.received
            if (Array.isArray(receivedData)) {
              // If backend returned a raw list despite validation, coerce it
              const parsed = stockArraySchema.parse(receivedData)
              items.value = parsed
              return items.value
            }
          } catch (parseError) {
            console.error('Error parsing stock data:', parseError)
          }
        }
        // Re-throw so callers can decide whether to swallow
        throw error
      } finally {
        loading.value = false
        queueMicrotask(() => {
          inFlight = null
        })
      }
    })()
  }

  async function fetchStock(force = false): Promise<StockItem[]> {
    // Return existing in-flight promise if one exists (unless forcing)
    if (loading.value && inFlight && !force) return inFlight

    // Early return if already have data and not forcing
    if (!force && items.value.length > 0) return items.value

    loading.value = true
    inFlight = startStockFetch({})

    return inFlight
  }

  // Non-blocking, abortable, one-shot fetch suitable for background refreshes
  function fetchStockSafe(options: StockFetchOptions = {}): Promise<StockItem[] | void> {
    const { signal, timeout, force = false } = options

    // If a request is already in-flight and not forcing, return it
    if (inFlight && !force) return inFlight

    // If we already have data and not forcing, resolve immediately
    if (!force && items.value.length > 0) return Promise.resolve(items.value)

    loading.value = true
    inFlight = startStockFetch({ signal, timeout })
    // Swallow rejections to remain non-blocking
    return inFlight.catch((error) => {
      console.warn('fetchStockSafe: background stock fetch failed (non-blocking):', error)
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
    const response = await api.purchasing_rest_stock_create(payload)
    return response
  }

  async function deactivate(id: string) {
    await api.purchasing_rest_stock_destroy(undefined, { params: { id } })
  }

  return { items, loading, fetchStock, fetchStockSafe, consumeStock, create, deactivate }
})
