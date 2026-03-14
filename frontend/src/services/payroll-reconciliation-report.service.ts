import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { debugLog } from '@/utils/debug'
import { toCsvString, downloadCsv } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import type { z } from 'zod'

export type PayrollReconciliationResponse = z.infer<typeof schemas.PayrollReconciliationResponse>

export async function fetchAlignedDateRange(startDate: string, endDate: string) {
  return await api.accounting_api_reports_payroll_date_range_retrieve({
    queries: { start_date: startDate, end_date: endDate },
  })
}

export async function fetchPayrollReconciliation(
  startDate: string,
  endDate: string,
): Promise<PayrollReconciliationResponse> {
  try {
    return await api.accounting_api_reports_payroll_reconciliation_retrieve({
      queries: { start_date: startDate, end_date: endDate },
    })
  } catch (error) {
    debugLog('Error fetching payroll reconciliation:', error)
    throw new Error('Failed to load payroll reconciliation report')
  }
}

export function exportPayrollReconciliationCsv(data: PayrollReconciliationResponse): void {
  const headers = ['Week', ...data.heatmap.staff_names]
  const rows = data.heatmap.rows.map((row) => [
    row.week_start,
    ...data.heatmap.staff_names.map((name) => {
      const val = row.cells[name]
      return val === null ? '' : val.toFixed(2)
    }),
  ])
  const csvContent = toCsvString(headers, rows)
  downloadCsv(csvContent, `payroll-reconciliation-${toLocalDateString()}`)
}
