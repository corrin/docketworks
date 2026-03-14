import { ref, type Ref } from 'vue'
import { api } from '../api/client'

interface JobFinancials {
  quoteTotal: number
  actualTotal: number
  invoiceTotal: number
  toBeInvoiced: number
}

export function useJobFinancials(jobId: Ref<string>) {
  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchJobFinancials = async (pricingMethodology?: string): Promise<JobFinancials> => {
    loading.value = true
    error.value = null

    try {
      // Fetch both cost summary and invoices in parallel
      const [costSummary, invoicesResponse] = await Promise.all([
        api.job_rest_jobs_costs_summary_retrieve({
          params: { job_id: jobId.value },
        }),
        api.job_rest_jobs_invoices_retrieve({
          params: { job_id: jobId.value },
        }),
      ])

      // Extract amounts from cost summary
      const quoteTotal = Number(costSummary.quote?.rev || 0)
      const actualTotal = Number(costSummary.actual?.rev || 0)

      // Calculate invoice total from invoices
      const invoices = invoicesResponse.invoices || []
      const invoiceTotal = invoices.reduce(
        (sum: number, invoice: { total_excl_tax?: number }) =>
          sum + Number(invoice.total_excl_tax || 0),
        0,
      )

      // Calculate amount to invoice based on pricing methodology
      const amountToInvoice =
        pricingMethodology === 'fixed_price' && quoteTotal > 0 ? quoteTotal : actualTotal

      const toBeInvoiced = Math.max(0, amountToInvoice - invoiceTotal)

      return {
        quoteTotal,
        actualTotal,
        invoiceTotal,
        toBeInvoiced,
      }
    } catch (err) {
      error.value = 'Failed to fetch job financial data'
      console.error('Error fetching job financials:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    fetchJobFinancials,
    loading: loading as Readonly<Ref<boolean>>,
    error: error as Readonly<Ref<string | null>>,
  }
}
