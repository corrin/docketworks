import { ref } from 'vue'
import { quoteService } from '@/services/quote.service'
import debug from 'debug'
import { z } from 'zod'
import { schemas } from '@/api/generated/api'

const log = debug('quote:import')

type QuoteImportStatusResponse = z.infer<typeof schemas.QuoteImportStatusResponse>

export function useQuoteImport() {
  const isLoading = ref(false)
  const currentQuote = ref<QuoteImportStatusResponse | null>(null)
  const error = ref<string | null>(null)

  async function loadQuoteStatus(jobId: string) {
    isLoading.value = true
    error.value = null

    try {
      log('Loading quote status for jobId:', jobId)
      currentQuote.value = await quoteService.getQuoteStatus(jobId)
      log('Quote status loaded:', currentQuote.value)
    } catch (err: unknown) {
      error.value = err instanceof Error ? err.message : 'Failed to load quote status'
      log('Failed to load quote status:', err)
    } finally {
      isLoading.value = false
    }
  }

  function reset() {
    currentQuote.value = null
    error.value = null
    isLoading.value = false
  }

  function clearError() {
    error.value = null
  }

  return {
    isLoading,
    currentQuote,
    error,
    loadQuoteStatus,
    reset,
    clearError,
  }
}
