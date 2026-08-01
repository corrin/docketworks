<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between bg-white p-4 rounded-lg border border-gray-200">
      <div>
        <h2 class="text-lg font-semibold text-gray-900">Finish Job</h2>
        <p class="text-sm text-gray-500">
          <span v-if="props.pricingMethodology === 'time_materials'">
            Compare Estimate and Actual cost sets for this Time & Materials job
          </span>
          <span v-else-if="!showQuoteColumn">
            Compare Estimate and Actual cost sets for this job (no quote available)
          </span>
          <span v-else>
            Compare Estimate, Quote, and Actual cost sets with visual performance indicators
          </span>
        </p>
      </div>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="text-center">
        <div
          class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"
        ></div>
        <p class="text-gray-500">Loading job financials...</p>
      </div>
    </div>

    <div
      v-else-if="loadError"
      data-automation-id="JobFinishTab-load-error"
      class="bg-white rounded-lg border border-red-200 p-6 text-center"
    >
      <p class="text-red-700 font-medium">Could not load this job's financials.</p>
      <p class="text-sm text-slate-600 mt-1">Reload the page.</p>
    </div>

    <template v-else-if="summary">
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 items-start">
        <section
          data-automation-id="JobFinishTab-balance"
          class="bg-white rounded-xl border border-slate-200 p-4"
        >
          <h3 class="text-base font-semibold text-gray-900">Customer balance</h3>

          <dl class="space-y-1.5 text-sm mt-3">
            <div class="flex justify-between">
              <dt class="text-slate-600">{{ jobValueLabel }}</dt>
              <dd class="tabular-nums font-medium">
                {{ formatCurrency(summary.job_value_excl_gst) }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-600">Already invoiced (excl GST)</dt>
              <dd class="tabular-nums font-medium">
                {{ formatCurrency(summary.valid_invoiced_excl_gst) }}
              </dd>
            </div>
            <div class="border-t border-slate-200 pt-1.5 flex justify-between">
              <dt class="text-slate-600">Still to invoice (excl GST)</dt>
              <dd
                data-automation-id="JobFinishTab-remaining-excl-gst"
                class="tabular-nums font-medium"
              >
                {{ formatCurrency(summary.remaining_to_invoice_excl_gst) }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-600">GST</dt>
              <dd data-automation-id="JobFinishTab-remaining-gst" class="tabular-nums font-medium">
                {{ formatCurrency(summary.remaining_gst) }}
              </dd>
            </div>
            <div v-if="summary.outstanding_invoiced_incl_gst > 0" class="flex justify-between">
              <dt class="text-slate-600">Unpaid invoices (incl GST)</dt>
              <dd
                data-automation-id="JobFinishTab-outstanding-incl-gst"
                class="tabular-nums font-medium"
              >
                {{ formatCurrency(summary.outstanding_invoiced_incl_gst) }}
              </dd>
            </div>
            <div class="border-t-2 border-slate-300 pt-2 mt-1 flex justify-between items-baseline">
              <dt class="font-semibold text-slate-900">Total to pay</dt>
              <dd
                data-automation-id="JobFinishTab-total-to-pay"
                class="tabular-nums text-2xl font-bold text-emerald-700"
              >
                {{ formatCurrency(summary.total_to_pay_incl_gst) }}
              </dd>
            </div>
          </dl>

          <div
            v-if="summary.over_invoiced_excl_gst > 0"
            data-automation-id="JobFinishTab-over-invoiced"
            class="mt-3 rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-900"
          >
            <strong
              >Job appears over-invoiced by
              {{ formatCurrency(summary.over_invoiced_excl_gst) }}</strong
            >
            (excl GST). The job value may be out of date, or invoicing may need correcting.
          </div>
        </section>

        <JobInvoiceCard
          :job-id="props.jobId"
          :pricing-methodology="props.pricingMethodology"
          :remaining-to-invoice="summary.remaining_to_invoice_excl_gst"
          :job-status="props.jobStatus"
          :paid="props.paid"
          @invoices-changed="reloadFinishSummary"
        />
      </div>

      <section
        data-automation-id="JobFinishTab-checklist"
        class="bg-white rounded-xl border border-slate-200 p-4"
      >
        <h3 class="text-base font-semibold text-gray-900">Completion checklist</h3>
        <p class="text-xs text-slate-500 mb-3">Self-checklist.</p>

        <div class="space-y-2">
          <label
            v-for="item in checklistItems"
            :key="item.key"
            class="flex items-start gap-2 text-sm cursor-pointer"
          >
            <input
              v-model="checklist[item.key]"
              type="checkbox"
              :data-automation-id="`JobFinishTab-checklist-${item.key}`"
              class="mt-0.5 h-4 w-4 rounded border-slate-300"
              :disabled="savingChecklistKey !== null"
              @change="onChecklistToggle(item.key)"
            />
            <span class="text-slate-800">{{ item.label }}</span>
          </label>
        </div>
      </section>
    </template>

    <div
      v-if="summary && !loadError"
      data-automation-id="JobFinishTab-labour-hours"
      class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm"
    >
      <div class="rounded-lg border border-slate-200 bg-white p-3">
        <div class="text-[11px] uppercase tracking-wide text-slate-500">Labour budget</div>
        <div
          data-automation-id="JobFinishTab-labour-budget"
          class="text-lg font-semibold tabular-nums text-slate-900"
        >
          {{ formatNumber(labourBudgetHours) }}
        </div>
      </div>
      <div class="rounded-lg border border-slate-200 bg-white p-3">
        <div class="text-[11px] uppercase tracking-wide text-slate-500">Hours used</div>
        <div
          data-automation-id="JobFinishTab-labour-used"
          class="text-lg font-semibold tabular-nums text-slate-900"
        >
          {{ formatNumber(actual.hours) }}
        </div>
      </div>
      <div
        class="rounded-lg border bg-white p-3"
        :class="labourOverrunHours > 0 ? 'border-red-200 bg-red-50' : 'border-slate-200'"
      >
        <div class="text-[11px] uppercase tracking-wide text-slate-500">
          {{ labourOverrunHours > 0 ? 'Overrun' : 'Hours remaining' }}
        </div>
        <div
          data-automation-id="JobFinishTab-labour-remaining"
          class="text-lg font-semibold tabular-nums"
          :class="labourOverrunHours > 0 ? 'text-red-700' : 'text-slate-900'"
        >
          {{ formatNumber(labourOverrunHours > 0 ? labourOverrunHours : labourRemainingHours) }}
        </div>
      </div>
    </div>

    <div v-if="summary && !loadError" class="overflow-x-auto">
      <table class="min-w-full bg-white rounded-lg border border-gray-200 text-sm">
        <thead>
          <tr class="bg-gray-50">
            <th class="py-3 px-4 text-left font-semibold text-gray-700">Metric</th>
            <th class="py-3 px-4 text-center font-semibold text-blue-700">Estimate</th>
            <th v-if="showQuoteColumn" class="py-3 px-4 text-center font-semibold text-green-700">
              Quote
            </th>
            <th class="py-3 px-4 text-center font-semibold text-orange-700">Actual</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="py-2 px-4 font-medium">Total Cost</td>
            <td class="py-2 px-4 text-center">{{ formatCurrency(estimate.cost) }}</td>
            <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
              {{ formatCurrency(quote.cost) }}
            </td>
            <td class="py-2 px-4 text-center">
              <span :class="costClass">
                {{ formatCurrency(actual.cost) }}
                <span v-if="costDiff !== 0">
                  <component :is="costIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                  <span :class="costDiff > 0 ? 'text-red-600' : 'text-green-600'">
                    {{ formatPercent(costDiff) }}
                  </span>
                </span>
              </span>
            </td>
          </tr>
          <tr>
            <td class="py-2 px-4 font-medium">Total Revenue</td>
            <td class="py-2 px-4 text-center">{{ formatCurrency(estimate.rev) }}</td>
            <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
              {{ formatCurrency(quote.rev) }}
            </td>
            <td class="py-2 px-4 text-center">
              <span :class="revenueClass">
                {{ formatCurrency(actual.rev) }}
                <span v-if="revenueDiff !== 0">
                  <component :is="revenueIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                  <span :class="revenueDiff > 0 ? 'text-green-600' : 'text-red-600'">
                    {{ formatPercent(revenueDiff) }}
                  </span>
                </span>
              </span>
            </td>
          </tr>
          <tr>
            <td class="py-2 px-4 font-medium">Profit Margin</td>
            <td class="py-2 px-4 text-center">{{ formatPercent(estimate.profitMargin) }}</td>
            <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
              {{ formatPercent(quote.profitMargin) }}
            </td>
            <td class="py-2 px-4 text-center">
              <span :class="profitClass">
                {{ formatPercent(actual.profitMargin) }}
                <span v-if="profitDiff !== 0">
                  <component :is="profitIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                  <span :class="profitDiff > 0 ? 'text-green-600' : 'text-red-600'">
                    {{ formatPercent(profitDiff) }}
                  </span>
                </span>
              </span>
            </td>
          </tr>
          <tr>
            <td class="py-2 px-4 font-medium">Total Hours</td>
            <td class="py-2 px-4 text-center">{{ formatNumber(estimate.hours) }}</td>
            <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
              {{ formatNumber(quote.hours) }}
            </td>
            <td class="py-2 px-4 text-center">
              <span :class="hoursClass">
                {{ formatNumber(actual.hours) }}
                <span v-if="hoursDiff !== 0">
                  <component :is="hoursIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                  <span :class="hoursDiff < 0 ? 'text-green-600' : 'text-red-600'">
                    {{ formatPercent(hoursDiff) }}
                  </span>
                </span>
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="showQuoteColumn" class="mt-6 flex flex-col md:flex-row gap-4">
        <div
          v-if="quotePerformance.status !== 'nodata'"
          class="flex-1 bg-white rounded-lg border border-gray-200 p-4 flex items-center gap-3"
        >
          <component
            :is="quoteAccuracyIcon"
            v-if="quoteAccuracyIcon"
            class="w-8 h-8"
            :class="quoteAccuracyClass"
          />
          <div>
            <div class="font-semibold text-gray-900">Quote Accuracy</div>
            <div class="text-lg font-bold" :class="quoteAccuracyClass">
              {{ formatPercent(quoteAccuracyDisplayValue) }}
            </div>
            <div class="text-xs text-gray-500">Deviation of actual cost from quoted cost</div>
          </div>
        </div>
        <div
          v-else
          class="flex-1 bg-gray-50 rounded-lg border border-gray-200 p-4 flex items-center gap-3"
        >
          <div class="w-8 h-8 bg-gray-300 rounded-full flex items-center justify-center">
            <span class="text-gray-500 text-sm">?</span>
          </div>
          <div>
            <div class="font-semibold text-gray-500">Quote Accuracy</div>
            <div class="text-sm text-gray-500">
              {{ !quote.cost ? 'No quote data available' : 'No actual data available' }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, reactive } from 'vue'
import { toast } from 'vue-sonner'
import { ArrowUp, ArrowDown, CheckCircle, AlertTriangle, XCircle } from 'lucide-vue-next'
import { api } from '../../api/client'
import debug from 'debug'
import JobInvoiceCard from './JobInvoiceCard.vue'
import { formatCurrency } from '@/utils/string-formatting'
import { schemas } from '../../api/generated/api'
import { z } from 'zod'

type JobCostSetSummaryOutput = z.infer<typeof schemas.JobCostSetSummary>
type NumericField<K extends keyof JobCostSetSummaryOutput> = Extract<
  JobCostSetSummaryOutput[K],
  number
>
type NormalizedCostSummary = {
  cost: NumericField<'cost'>
  rev: NumericField<'rev'>
  hours: NumericField<'hours'>
  profitMargin: number
}
type JobCostSummaryResponse = z.infer<typeof schemas.JobCostSummaryResponse>

const props = defineProps<{
  jobId: string
  pricingMethodology: string
  jobStatus?: string
  paid?: boolean
}>()

const loading = ref(true)
const hasValidQuoteData = ref(false)

const zeroSummary = (): NormalizedCostSummary => ({
  cost: 0,
  rev: 0,
  hours: 0,
  profitMargin: 0,
})

const log = debug('job:finish')

type FinishJobSummary = z.infer<typeof schemas.FinishJobSummary>
type JobCompletionChecklist = z.infer<typeof schemas.JobCompletionChecklist>
type ChecklistItemKey = keyof JobCompletionChecklist

// No fabricated placeholder: until the server answers there is no balance, and a
// failed load must not render as a settled $0 job.
const summary = ref<FinishJobSummary | null>(null)
const loadError = ref(false)
const checklist = reactive<JobCompletionChecklist>({
  foreman_signed_off: false,
  timesheets_collected: false,
  materials_checked: false,
  customer_called: false,
  released: false,
})
const savingChecklistKey = ref<ChecklistItemKey | null>(null)

const allChecklistItems: Array<{ key: ChecklistItemKey; label: string }> = [
  { key: 'foreman_signed_off', label: 'Has the supervisor signed off the job?' },
  { key: 'timesheets_collected', label: "Have you collected today's timesheet entries?" },
  { key: 'materials_checked', label: 'Are all materials used written correctly on the job sheet?' },
  { key: 'customer_called', label: 'Have you called the customer?' },
  { key: 'released', label: 'Has the job been handed over?' },
]

// Timesheets only exist to invoice on a T&M job; a quoted job is never asked.
const checklistItems = computed(() =>
  props.pricingMethodology === 'time_materials'
    ? allChecklistItems
    : allChecklistItems.filter((item) => item.key !== 'timesheets_collected'),
)

const jobValueLabel = computed(() =>
  props.pricingMethodology === 'fixed_price'
    ? 'Quote total (excl GST)'
    : 'Job value to date (excl GST)',
)

const estimate = reactive<NormalizedCostSummary>(zeroSummary())
const quote = reactive<NormalizedCostSummary>(zeroSummary())
const actual = reactive<NormalizedCostSummary>(zeroSummary())

const ensureSummary = (s?: JobCostSetSummaryOutput | null): NormalizedCostSummary => ({
  cost: s?.cost ?? 0,
  rev: s?.rev ?? 0,
  hours: s?.hours ?? 0,
  profitMargin: s?.profitMargin ?? 0,
})

async function loadFinishSummary() {
  const response = await api.job_jobs_finish_retrieve({ params: { job_id: props.jobId } })
  summary.value = response.summary
  Object.assign(checklist, response.checklist)
}

async function loadCostSummary() {
  const resp: JobCostSummaryResponse = await api.job_jobs_costs_summary_retrieve({
    params: { job_id: props.jobId },
  })

  Object.assign(estimate, ensureSummary(resp.estimate))
  Object.assign(quote, ensureSummary(resp.quote))
  Object.assign(actual, ensureSummary(resp.actual))

  hasValidQuoteData.value =
    !!resp.quote && ((resp.quote.cost ?? 0) > 0 || (resp.quote.rev ?? 0) > 0)
}

async function loadAll() {
  loading.value = true
  loadError.value = false
  try {
    await Promise.all([loadFinishSummary(), loadCostSummary()])
  } catch (error) {
    log('Failed to load Finish Job data: %o', error)
    toast.error('Failed to load job financials')
    // Leave summary null and say so. Showing zeros here would tell staff a job
    // is settled when we simply could not read it.
    summary.value = null
    loadError.value = true
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

// Invoicing changed the balance, so a failed reload must say so rather than
// leave the pre-invoice figure on screen looking current.
async function reloadFinishSummary() {
  try {
    await loadFinishSummary()
  } catch (error) {
    log('Failed to reload Finish Job balance: %o', error)
    summary.value = null
    loadError.value = true
    toast.error('Invoice saved, but the balance could not be refreshed. Reload the job.')
  }
}

// v-model has already applied the new value optimistically; this persists it and
// puts it back if the server refuses, so a tick never survives a failed save.
async function onChecklistToggle(key: ChecklistItemKey) {
  const checked = checklist[key]
  savingChecklistKey.value = key
  try {
    const response = await api.job_jobs_finish_partial_update(
      { [key]: checked },
      { params: { job_id: props.jobId } },
    )
    Object.assign(checklist, response.checklist)
  } catch (error) {
    log('Failed to save checklist item %s: %o', key, error)
    toast.error('Failed to save checklist')
    checklist[key] = !checked
  } finally {
    savingChecklistKey.value = null
  }
}

// --- KAN-222 labour hours ---

const labourBudgetHours = computed(() =>
  props.pricingMethodology === 'fixed_price' && hasValidQuoteData.value
    ? quote.hours
    : estimate.hours,
)
const labourRemainingHours = computed(() => Math.max(labourBudgetHours.value - actual.hours, 0))
const labourOverrunHours = computed(() => Math.max(actual.hours - labourBudgetHours.value, 0))

const showQuoteColumn = computed(() => {
  if (props.pricingMethodology === 'time_materials') return false
  return hasValidQuoteData.value || quote.cost > 0 || quote.rev > 0
})

function percentDiff(actualNum: number, refNum: number): number {
  if (!refNum) return 0
  return ((actualNum - refNum) / refNum) * 100
}

const costRef = computed(() =>
  props.pricingMethodology === 'time_materials' || !showQuoteColumn.value
    ? estimate.cost
    : quote.cost,
)
const revRef = computed(() =>
  props.pricingMethodology === 'time_materials' || !showQuoteColumn.value
    ? estimate.rev
    : quote.rev,
)
const pmRef = computed(() =>
  props.pricingMethodology === 'time_materials' || !showQuoteColumn.value
    ? estimate.profitMargin
    : quote.profitMargin,
)
const hoursRef = computed(() =>
  props.pricingMethodology === 'time_materials' || !showQuoteColumn.value
    ? estimate.hours
    : quote.hours,
)

const costDiff = computed(() => percentDiff(actual.cost, costRef.value))
const revenueDiff = computed(() => percentDiff(actual.rev, revRef.value))
const profitDiff = computed(() => percentDiff(actual.profitMargin, pmRef.value))
const hoursDiff = computed(() => percentDiff(actual.hours, hoursRef.value))

const costClass = computed(() =>
  costDiff.value > 0 ? 'text-red-600 font-bold' : 'text-green-600 font-bold',
)
const costIcon = computed(() =>
  costDiff.value > 0 ? ArrowUp : costDiff.value < 0 ? ArrowDown : null,
)

const revenueClass = computed(() =>
  revenueDiff.value >= 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold',
)
const revenueIcon = computed(() =>
  revenueDiff.value > 0 ? ArrowUp : revenueDiff.value < 0 ? ArrowDown : null,
)

const profitClass = computed(() =>
  profitDiff.value >= 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold',
)
const profitIcon = computed(() =>
  profitDiff.value > 0 ? ArrowUp : profitDiff.value < 0 ? ArrowDown : null,
)

const hoursClass = computed(() =>
  hoursDiff.value <= 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold',
)
const hoursIcon = computed(() =>
  hoursDiff.value < 0 ? ArrowDown : hoursDiff.value > 0 ? ArrowUp : null,
)

const quotePerformance = computed(() => {
  if (!showQuoteColumn.value || !hasValidQuoteData.value || quote.cost === 0) {
    return { status: 'nodata' as const, deviation: 0 }
  }
  const deviation = Math.abs(percentDiff(actual.cost, quote.cost))
  if (deviation <= 20) return { status: 'good' as const, deviation }
  if (deviation <= 40) return { status: 'amber' as const, deviation }
  return { status: 'red' as const, deviation }
})

const quoteAccuracyIcon = computed(() => {
  switch (quotePerformance.value.status) {
    case 'good':
      return CheckCircle
    case 'amber':
      return AlertTriangle
    case 'red':
      return XCircle
    default:
      return null
  }
})

const quoteAccuracyClass = computed(() => {
  switch (quotePerformance.value.status) {
    case 'good':
      return 'text-green-600'
    case 'amber':
      return 'text-yellow-600'
    case 'red':
      return 'text-red-600'
    default:
      return 'text-gray-500'
  }
})

const quoteAccuracyDisplayValue = computed(() => {
  if (quotePerformance.value.status === 'nodata') return 0
  return percentDiff(actual.cost, quote.cost)
})

function formatPercent(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}
function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)
}
</script>

<style scoped>
table {
  border-collapse: separate;
  border-spacing: 0;
}
th,
td {
  border-bottom: 1px solid #e5e7eb;
}
th:last-child,
td:last-child {
  border-right: none;
}
</style>
