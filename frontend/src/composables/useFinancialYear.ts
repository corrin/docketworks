import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { toLocalDateString } from '@/utils/dateUtils'

/**
 * Returns financial year helpers based on the company defaults setting.
 * The store must be loaded before calling these functions.
 */
export function useFinancialYear() {
  const store = useCompanyDefaultsStore()

  /** 0-indexed start month from company defaults, falls back to March (NZ standard April 1 = month index 3) */
  const getFyStartMonth = (): number => {
    const m = store.companyDefaults?.financial_year_start_month
    // Backend stores 1-indexed month; convert to 0-indexed
    return m != null ? m - 1 : 3
  }

  const getFinancialYearStart = (date: Date): Date => {
    const fyMonth = getFyStartMonth()
    const year = date.getMonth() >= fyMonth ? date.getFullYear() : date.getFullYear() - 1
    return new Date(year, fyMonth, 1)
  }

  const getFinancialYearEnd = (date: Date): Date => {
    const fyStart = getFinancialYearStart(date)
    return new Date(fyStart.getFullYear() + 1, fyStart.getMonth(), 0) // last day of month before FY start
  }

  const getDateRange = (
    preset: 'thisFinancialYear' | 'lastFinancialYear',
  ): { startDate: string; endDate: string } => {
    const now = new Date()

    if (preset === 'thisFinancialYear') {
      return {
        startDate: toLocalDateString(getFinancialYearStart(now)),
        endDate: toLocalDateString(getFinancialYearEnd(now)),
      }
    }

    // lastFinancialYear: shift back by one year to land in the previous FY
    const fyStart = getFinancialYearStart(now)
    const lastFyStart = new Date(fyStart.getFullYear() - 1, fyStart.getMonth(), 1)
    const lastFyEnd = new Date(fyStart.getFullYear(), fyStart.getMonth(), 0) // day before this FY starts
    return {
      startDate: toLocalDateString(lastFyStart),
      endDate: toLocalDateString(lastFyEnd),
    }
  }

  return {
    getFinancialYearStart,
    getFinancialYearEnd,
    getDateRange,
  }
}
