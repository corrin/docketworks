import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'
import debug from 'debug'

const log = debug('cost:api')

type CostLineRequest = z.infer<typeof schemas.CostLineCreateUpdateRequest>
type PatchedCostLineRequest = z.infer<typeof schemas.PatchedCostLineCreateUpdateRequest>
type CostLineResponse = z.infer<typeof schemas.CostLine>
export type TimesheetEntriesResponse = z.infer<typeof schemas.ModernTimesheetEntryGetResponse>
type StockConsumeResponse = z.infer<typeof schemas.StockConsumeResponse>

export const getTimesheetEntries = async (
  staffId: string,
  date: string,
): Promise<TimesheetEntriesResponse> => {
  try {
    return await api.job_timesheet_entries_retrieve({
      queries: { staff_id: staffId, date },
    })
  } catch (error) {
    log('Error fetching timesheet entries:', error)
    throw error
  }
}

export const createCostLine = async (
  jobId: string | number,
  kind: 'estimate' | 'quote' | 'actual',
  payload: CostLineRequest,
): Promise<CostLineResponse> => {
  log('Creating cost line:')
  log(' - Job ID:', jobId)
  log(' - Kind:', kind)
  log(' - Payload:', payload)

  const now = new Date().toISOString()
  const body: CostLineRequest = {
    ...payload,
    kind: payload.kind ?? kind,
    ext_refs: payload.ext_refs ?? {},
    meta: payload.meta ?? {},
    accounting_date: payload.accounting_date ?? now,
    // An absent description is null, never ''. Callers building a row from
    // form state pass '' for an untouched field, so normalise it here rather
    // than in each of them.
    ...('desc' in payload ? { desc: payload.desc || null } : {}),
  }

  const result =
    kind === 'actual'
      ? await api.job_jobs_cost_sets_actual_cost_lines_create(body, {
          params: { job_id: String(jobId) },
        })
      : await api.job_jobs_cost_sets_cost_lines_create(body, {
          params: { job_id: String(jobId), kind },
        })

  log('Created cost line result:', result)
  return schemas.CostLine.parse(result)
}

export const updateCostLine = async (
  id: string,
  payload: PatchedCostLineRequest,
): Promise<CostLineResponse> => {
  // As in create: a cleared description is null, never ''.
  const body: PatchedCostLineRequest = {
    ...payload,
    ...('desc' in payload ? { desc: payload.desc || null } : {}),
  }
  const result = await api.job_cost_lines_partial_update(body, {
    params: { cost_line_id: id },
  })
  return schemas.CostLine.parse(result)
}

export const approveCostLine = async (id: string): Promise<CostLineResponse> => {
  const response = await api.approveCostLine(undefined, { params: { cost_line_id: id } })
  const parsed: StockConsumeResponse = schemas.StockConsumeResponse.parse(response)
  return schemas.CostLine.parse(parsed.line)
}

export const deleteCostLine = async (id: string): Promise<void> => {
  log('Starting DELETE request for cost line ID:', id)
  log('Deleting cost line:', id)

  try {
    await api.job_cost_lines_delete_destroy(undefined, {
      params: { cost_line_id: id },
    })
    log('DELETE request completed successfully')
    log('Successfully deleted cost line:', id)
  } catch (error) {
    log('DELETE request failed:', error)
    log('Delete failed:', error)
    throw error
  }
}

export const costlineService = {
  createCostLine,
  updateCostLine,
  deleteCostLine,
  approveCostLine,
}
