import { isIsoMonthString } from '@/lib/dates'

import type { KpiDecimals, KpiTarget } from './kpiDisplay'

/**
 * The report's settings, all in the URL (Xero's model) so a shared link
 * carries the month, the ladder and the precision the sender was looking at.
 * Each is optional here; the route applies the defaults.
 */
export interface KpiSearch {
  month?: string
  target?: KpiTarget
  decimals?: KpiDecimals
}

/**
 * Read the report settings off the URL, dropping anything malformed so a
 * hand-edited link falls back to the defaults rather than reaching the month
 * helpers (which throw) or the API (which 422s).
 */
export function kpiSearchFromUrl(search: Record<string, unknown>): KpiSearch {
  return {
    month:
      typeof search.month === 'string' && isIsoMonthString(search.month) ? search.month : undefined,
    target: search.target === 'hours' || search.target === 'dollars' ? search.target : undefined,
    decimals: search.decimals === 0 || search.decimals === 2 ? search.decimals : undefined,
  }
}
