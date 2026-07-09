import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'

type SearchDomain = 'company' | 'kanban' | 'stock'

export async function logSearchResultClick(params: {
  domain: SearchDomain
  query: string
  selectedResultId: string
  selectedLabel?: string
  selectedRank?: number | null
  resultCount?: number
  source?: string
  filters?: Record<string, unknown>
  metadata?: Record<string, unknown>
}): Promise<void> {
  const trimmedQuery = params.query.trim()
  const hasFilters = params.filters && Object.keys(params.filters).length > 0
  if (trimmedQuery.length < 3 && !hasFilters) {
    return
  }

  try {
    await api.search_events_click_create({
      domain: params.domain,
      query: trimmedQuery,
      selected_result_id: params.selectedResultId,
      selected_label: params.selectedLabel ?? '',
      selected_rank: params.selectedRank ?? null,
      result_count: params.resultCount ?? 0,
      source: params.source ?? '',
      filters: params.filters ?? {},
      metadata: params.metadata ?? {},
    })
  } catch (error) {
    debugLog('Failed to log search click:', error)
  }
}
