import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

export type QuoteSpreadsheet = z.infer<typeof schemas.QuoteSpreadsheet>
export type PreviewQuoteResponse = z.infer<typeof schemas.PreviewQuoteResponse>
export type ApplyQuoteResponse = z.infer<typeof schemas.ApplyQuoteResponse>
export type Job = z.infer<typeof schemas.Job>
export type LinkQuoteSheetRequest = z.infer<typeof schemas.LinkQuoteSheetRequest>
export type QuoteImportStatusResponse = z.infer<typeof schemas.QuoteImportStatusResponse>
export type JobDetailResponse = z.infer<typeof schemas.JobDetailResponse>

class QuoteService {
  async linkQuote(jobId: string, templateUrl?: string): Promise<QuoteSpreadsheet | null> {
    const payload: LinkQuoteSheetRequest = templateUrl ? { template_url: templateUrl } : {}

    await api.job_rest_jobs_quote_link_create(payload, { params: { id: jobId } })

    const jobResponse = await api.getJobSummary({ params: { job_id: jobId } })
    return jobResponse.data?.job?.quote_sheet ?? null
  }

  async previewQuote(jobId: string): Promise<PreviewQuoteResponse> {
    return api.job_rest_jobs_quote_preview_create({}, { params: { id: jobId } })
  }

  async applyQuote(jobId: string): Promise<ApplyQuoteResponse> {
    return api.job_rest_jobs_quote_apply_create({ success: true }, { params: { id: jobId } })
  }

  hasLinkedSheet(job: Job): boolean {
    return !!job?.quote_sheet?.sheet_url
  }

  getSheetUrl(job: Job): string | null {
    return job?.quote_sheet?.sheet_url || null
  }

  async getQuoteStatus(jobId: string): Promise<QuoteImportStatusResponse> {
    return await api.job_rest_jobs_quote_status_retrieve({ params: { job_id: jobId } })
  }
}

export const quoteService = new QuoteService()
