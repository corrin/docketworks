<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between bg-white p-4 rounded-lg border border-gray-200">
      <div>
        <h2 class="text-lg font-semibold text-gray-900">Cost Analysis</h2>
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
        <p class="text-gray-500">Loading cost data...</p>
      </div>
    </div>

    <div v-else class="overflow-x-auto">
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
}>()

const loading = ref(true)
const hasValidQuoteData = ref(false)

const zeroSummary = (): NormalizedCostSummary => ({
  cost: 0,
  rev: 0,
  hours: 0,
  profitMargin: 0,
})

const estimate = reactive<NormalizedCostSummary>(zeroSummary())
const quote = reactive<NormalizedCostSummary>(zeroSummary())
const actual = reactive<NormalizedCostSummary>(zeroSummary())

const ensureSummary = (s?: JobCostSetSummaryOutput | null): NormalizedCostSummary => ({
  cost: s?.cost ?? 0,
  rev: s?.rev ?? 0,
  hours: s?.hours ?? 0,
  profitMargin: s?.profitMargin ?? 0,
})

async function loadAll() {
  loading.value = true
  try {
    const resp: JobCostSummaryResponse = await api.job_rest_jobs_costs_summary_retrieve({
      params: { job_id: props.jobId },
    })

    Object.assign(estimate, ensureSummary(resp.estimate))
    Object.assign(quote, ensureSummary(resp.quote))
    Object.assign(actual, ensureSummary(resp.actual))

    hasValidQuoteData.value =
      !!resp.quote && ((resp.quote.cost ?? 0) > 0 || (resp.quote.rev ?? 0) > 0)
  } catch (error) {
    console.error('Failed to load cost summary:', error)
    toast.error('Failed to load cost analysis')
    Object.assign(estimate, zeroSummary())
    Object.assign(quote, zeroSummary())
    Object.assign(actual, zeroSummary())
    hasValidQuoteData.value = false
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

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
