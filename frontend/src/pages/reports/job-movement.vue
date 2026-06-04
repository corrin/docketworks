<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1
              data-automation-id="JobMovementReport-title"
              class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3"
            >
              <TrendingUp class="w-8 h-8 text-indigo-400" />
              Job Movement Report
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportToCsv"
                :disabled="loading || !reportData"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="default"
                @click="loadData"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Refresh
              </Button>
            </div>
          </div>

          <!-- Date Range Filters -->
          <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
            <div class="flex flex-wrap items-center gap-4">
              <div class="flex items-center gap-2">
                <label for="start-date" class="text-sm font-medium text-gray-700">
                  Start Date:
                </label>
                <input
                  id="start-date"
                  v-model="dateRange.startDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="() => loadData()"
                />
              </div>
              <div class="flex items-center gap-2">
                <label for="end-date" class="text-sm font-medium text-gray-700"> End Date: </label>
                <input
                  id="end-date"
                  v-model="dateRange.endDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="() => loadData()"
                />
              </div>
              <div class="flex gap-2">
                <Button variant="outline" size="sm" @click="setDateRange('thisFortnight')">
                  This Fortnight
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  data-automation-id="JobMovementReport-last-fortnight"
                  @click="setDateRange('lastFortnight')"
                >
                  Last Fortnight
                </Button>
                <Button variant="outline" size="sm" @click="setDateRange('lastMonth')">
                  Last Month
                </Button>
                <Button variant="outline" size="sm" @click="setDateRange('lastQuarter')">
                  Last Quarter
                </Button>
              </div>
            </div>
            <!-- Baseline toggle -->
            <div class="flex items-center gap-4 mt-4 pt-4 border-t border-slate-200">
              <label class="flex items-center gap-2 cursor-pointer">
                <input
                  v-model="includeBaseline"
                  type="checkbox"
                  class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  @change="() => loadData()"
                />
                <span class="text-sm font-medium text-gray-700">Include baseline comparison</span>
              </label>
              <div v-if="includeBaseline" class="flex items-center gap-2">
                <label for="baseline-days" class="text-sm text-gray-600">Days:</label>
                <input
                  id="baseline-days"
                  v-model.number="baselineDays"
                  type="number"
                  min="30"
                  max="730"
                  class="w-20 rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="() => loadData()"
                />
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            data-automation-id="JobMovementReport-loading"
            class="flex items-center justify-center py-12"
          >
            <RefreshCw class="h-8 w-8 animate-spin text-indigo-500" />
            <span class="ml-2 text-lg text-gray-600">Loading job movement data...</span>
          </div>

          <!-- Error State -->
          <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="flex items-center">
              <AlertCircle class="h-5 w-5 text-red-400 mr-2" />
              <span class="text-red-800">{{ error }}</span>
            </div>
          </div>

          <!-- Report Content -->
          <template v-else-if="reportData">
            <!-- Summary Cards -->
            <div
              data-automation-id="JobMovementReport-summary-cards"
              class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
            >
              <div
                data-automation-id="JobMovementReport-draft-jobs-card"
                class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
              >
                <div class="flex items-center justify-between">
                  <div>
                    <p class="text-sm font-medium text-gray-600">Draft Jobs Created</p>
                    <p
                      data-automation-id="JobMovementReport-draft-jobs-count"
                      class="text-2xl font-bold text-gray-900"
                    >
                      {{ reportData.metrics.draft_jobs_created.count }}
                    </p>
                    <p v-if="reportData.baseline" class="text-xs text-gray-500 mt-1">
                      Avg:
                      {{ reportData.baseline.weekly_averages.draft_jobs_created.toFixed(1) }}/week
                    </p>
                  </div>
                  <FileText class="h-8 w-8 text-blue-500" />
                </div>
              </div>

              <div
                data-automation-id="JobMovementReport-quotes-submitted-card"
                class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
              >
                <div class="flex items-center justify-between">
                  <div>
                    <p class="text-sm font-medium text-gray-600">Quotes Submitted</p>
                    <p
                      data-automation-id="JobMovementReport-quotes-submitted-count"
                      class="text-2xl font-bold text-gray-900"
                    >
                      {{ reportData.metrics.quotes_submitted.count }}
                    </p>
                    <p v-if="reportData.baseline" class="text-xs text-gray-500 mt-1">
                      Avg:
                      {{ reportData.baseline.weekly_averages.quotes_submitted.toFixed(1) }}/week
                    </p>
                  </div>
                  <Send class="h-8 w-8 text-yellow-500" />
                </div>
              </div>

              <div
                data-automation-id="JobMovementReport-jobs-won-card"
                class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
              >
                <div class="flex items-center justify-between">
                  <div>
                    <p class="text-sm font-medium text-gray-600">Jobs Won</p>
                    <p
                      data-automation-id="JobMovementReport-jobs-won-count"
                      class="text-2xl font-bold text-gray-900"
                    >
                      {{ reportData.metrics.jobs_won.count }}
                    </p>
                    <p v-if="reportData.baseline" class="text-xs text-gray-500 mt-1">
                      Avg: {{ reportData.baseline.weekly_averages.jobs_won.toFixed(1) }}/week
                    </p>
                  </div>
                  <CheckCircle class="h-8 w-8 text-green-500" />
                </div>
              </div>

              <div
                data-automation-id="JobMovementReport-conversion-rate-card"
                class="bg-white rounded-lg shadow-sm border border-slate-200 p-4"
              >
                <div class="flex items-center justify-between">
                  <div>
                    <p class="text-sm font-medium text-gray-600">Draft Conversion Rate</p>
                    <p
                      data-automation-id="JobMovementReport-conversion-rate-value"
                      class="text-2xl font-bold text-gray-900"
                    >
                      {{ formatPercentage(reportData.metrics.draft_conversion_rate.rate) }}
                    </p>
                    <p v-if="reportData.baseline" class="text-xs text-gray-500 mt-1">
                      Baseline:
                      {{ formatPercentage(reportData.baseline.rates.draft_conversion_rate) }}
                    </p>
                  </div>
                  <TrendingUp class="h-8 w-8 text-purple-500" />
                </div>
              </div>
            </div>

            <!-- Secondary Metrics -->
            <div
              data-automation-id="JobMovementReport-additional-metrics"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-6"
            >
              <h3 class="text-lg font-medium text-gray-900 mb-4">Additional Metrics</h3>
              <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
                <!-- Quote Acceptance -->
                <div>
                  <p class="text-sm font-medium text-gray-600">Quote Acceptance Rate</p>
                  <p class="text-xl font-bold text-gray-900">
                    {{ formatPercentage(reportData.metrics.quote_acceptance_rate.rate) }}
                  </p>
                  <p class="text-xs text-gray-500">
                    {{ reportData.metrics.quote_acceptance_rate.numerator }} of
                    {{ reportData.metrics.quote_acceptance_rate.denominator }} quotes accepted
                  </p>
                  <p v-if="reportData.baseline" class="text-xs text-gray-400 mt-1">
                    Baseline:
                    {{ formatPercentage(reportData.baseline.rates.quote_acceptance_rate) }}
                  </p>
                </div>

                <!-- Workflow Paths -->
                <div>
                  <p class="text-sm font-medium text-gray-600">Workflow Distribution</p>
                  <div class="mt-2 space-y-1">
                    <div class="flex justify-between text-sm">
                      <span class="text-gray-600">Through Quotes:</span>
                      <span class="font-medium">{{
                        reportData.metrics.workflow_paths.through_quotes
                      }}</span>
                    </div>
                    <div class="flex justify-between text-sm">
                      <span class="text-gray-600">Direct (Skip Quotes):</span>
                      <span class="font-medium">{{
                        reportData.metrics.workflow_paths.skip_quotes
                      }}</span>
                    </div>
                    <div class="flex justify-between text-sm">
                      <span class="text-gray-600">Still Draft:</span>
                      <span class="font-medium">{{
                        reportData.metrics.workflow_paths.still_draft
                      }}</span>
                    </div>
                  </div>
                </div>

                <!-- Quote Usage -->
                <div>
                  <p class="text-sm font-medium text-gray-600">Quote Usage Rate</p>
                  <p class="text-xl font-bold text-gray-900">
                    {{ formatPercentage(reportData.metrics.workflow_paths.quote_usage_percent) }}
                  </p>
                  <p class="text-xs text-gray-500">Jobs that went through the quote process</p>
                  <p v-if="reportData.baseline" class="text-xs text-gray-400 mt-1">
                    Baseline: {{ formatPercentage(reportData.baseline.rates.quote_usage_rate) }}
                  </p>
                </div>
              </div>
            </div>

            <!-- Baseline Comparison Table -->
            <div
              v-if="reportData.baseline"
              class="bg-white rounded-lg shadow-sm border border-slate-200 p-6"
            >
              <h3 class="text-lg font-medium text-gray-900 mb-4">
                Baseline Comparison ({{ reportData.baseline.period_days }} days,
                {{ reportData.baseline.weeks.toFixed(1) }} weeks)
              </h3>
              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                  <thead class="bg-gray-50">
                    <tr>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Metric
                      </th>
                      <th
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Current Period
                      </th>
                      <th
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Weekly Average
                      </th>
                      <th
                        class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Baseline Total
                      </th>
                    </tr>
                  </thead>
                  <tbody class="bg-white divide-y divide-gray-200">
                    <tr>
                      <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        Draft Jobs Created
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.metrics.draft_jobs_created.count }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.baseline.weekly_averages.draft_jobs_created.toFixed(1) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                        {{ reportData.baseline.totals.draft_jobs_created }}
                      </td>
                    </tr>
                    <tr>
                      <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        Quotes Submitted
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.metrics.quotes_submitted.count }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.baseline.weekly_averages.quotes_submitted.toFixed(1) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                        {{ reportData.baseline.totals.quotes_submitted }}
                      </td>
                    </tr>
                    <tr>
                      <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        Quotes Accepted
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.metrics.quotes_accepted.count }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.baseline.weekly_averages.quotes_accepted.toFixed(1) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                        {{ reportData.baseline.totals.quotes_accepted }}
                      </td>
                    </tr>
                    <tr>
                      <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        Jobs Won
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.metrics.jobs_won.count }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.baseline.weekly_averages.jobs_won.toFixed(1) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                        {{ reportData.baseline.totals.jobs_won }}
                      </td>
                    </tr>
                    <tr>
                      <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        Rejected
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.metrics.jobs_won.rejected }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 text-right">
                        {{ reportData.baseline.weekly_averages.rejected.toFixed(1) }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-right">
                        {{ reportData.baseline.totals.rejected }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- Details Section (Collapsible) -->
            <div
              v-if="reportData.details"
              class="bg-white rounded-lg shadow-sm border border-slate-200"
            >
              <button
                @click="showDetails = !showDetails"
                class="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-gray-50"
              >
                <h3 class="text-lg font-medium text-gray-900">Job Details</h3>
                <ChevronDown
                  class="h-5 w-5 text-gray-500 transition-transform"
                  :class="{ 'rotate-180': showDetails }"
                />
              </button>

              <div v-if="showDetails" class="px-6 pb-6 space-y-6">
                <!-- Draft Jobs -->
                <JobDetailTable
                  v-if="reportData.details.draft_jobs.length"
                  title="Draft Jobs"
                  :jobs="reportData.details.draft_jobs"
                />

                <!-- Quotes Submitted -->
                <JobDetailTable
                  v-if="reportData.details.quotes_submitted.length"
                  title="Quotes Submitted"
                  :jobs="reportData.details.quotes_submitted"
                />

                <!-- Quotes Accepted -->
                <JobDetailTable
                  v-if="reportData.details.quotes_accepted.length"
                  title="Quotes Accepted"
                  :jobs="reportData.details.quotes_accepted"
                />

                <!-- Jobs Won -->
                <JobDetailTable
                  v-if="reportData.details.jobs_won.length"
                  title="Jobs Won"
                  :jobs="reportData.details.jobs_won"
                />

                <!-- Still Draft -->
                <JobDetailTable
                  v-if="reportData.details.jobs_still_draft.length"
                  title="Still Draft"
                  :jobs="reportData.details.jobs_still_draft"
                />

                <!-- Rejected -->
                <JobDetailTable
                  v-if="reportData.details.jobs_rejected.length"
                  title="Rejected"
                  :jobs="reportData.details.jobs_rejected"
                />
              </div>
            </div>

            <!-- Toggle Details Button (if not already loaded) -->
            <div v-if="!reportData.details" class="flex justify-center">
              <Button variant="outline" @click="loadDataWithDetails" :disabled="loading">
                <List class="w-4 h-4 mr-2" />
                Load Job Details
              </Button>
            </div>
          </template>

          <!-- Empty State -->
          <div v-else class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center">
            <TrendingUp class="mx-auto h-12 w-12 text-gray-400" />
            <h3 class="mt-2 text-sm font-medium text-gray-900">No data available</h3>
            <p class="mt-1 text-sm text-gray-500">
              Select a date range to view job movement metrics.
            </p>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  TrendingUp,
  Download,
  RefreshCw,
  AlertCircle,
  FileText,
  Send,
  CheckCircle,
  ChevronDown,
  List,
} from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { jobMovementReportService } from '@/services/job-movement-report.service'
import { toLocalDateString } from '@/utils/dateUtils'
import type {
  JobMovementReportResponse,
  JobMovementParams,
  JobMovementJobDetail,
} from '@/types/job-movement.types'

// Inline component for job detail tables
const JobDetailTable = {
  props: {
    title: { type: String, required: true },
    jobs: { type: Array as () => JobMovementJobDetail[], required: true },
  },
  template: `
    <div>
      <h4 class="text-sm font-medium text-gray-700 mb-2">{{ title }} ({{ jobs.length }})</h4>
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200 text-sm">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Job #</th>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Client</th>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Created</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="job in jobs" :key="job.id" class="hover:bg-gray-50">
              <td class="px-4 py-2 whitespace-nowrap font-medium text-indigo-600">{{ job.job_number }}</td>
              <td class="px-4 py-2 whitespace-nowrap">{{ job.name }}</td>
              <td class="px-4 py-2 whitespace-nowrap">{{ job.client_name }}</td>
              <td class="px-4 py-2 whitespace-nowrap">{{ job.status }}</td>
              <td class="px-4 py-2 whitespace-nowrap text-gray-500">{{ job.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
}

const loading = ref(false)
const error = ref<string | null>(null)
const reportData = ref<JobMovementReportResponse | null>(null)
const showDetails = ref(false)

const dateRange = ref({
  startDate: '',
  endDate: '',
})

const includeBaseline = ref(true)
const baselineDays = ref(365)

const formatPercentage = (value: number): string => {
  return `${value.toFixed(1)}%`
}

const getMonday = (date: Date): Date => {
  const d = new Date(date)
  const day = d.getDay()
  const diff = d.getDate() - day + (day === 0 ? -6 : 1) // Adjust when day is Sunday
  d.setDate(diff)
  return d
}

const setDateRange = (period: 'thisFortnight' | 'lastFortnight' | 'lastMonth' | 'lastQuarter') => {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()

  switch (period) {
    case 'thisFortnight': {
      const monday = getMonday(now)
      const sunday = new Date(monday)
      sunday.setDate(monday.getDate() + 13) // 2 weeks = 14 days, so +13 from Monday
      dateRange.value.startDate = toLocalDateString(monday)
      dateRange.value.endDate = toLocalDateString(sunday)
      break
    }
    case 'lastFortnight': {
      const thisMonday = getMonday(now)
      const lastFortnightMonday = new Date(thisMonday)
      lastFortnightMonday.setDate(thisMonday.getDate() - 14)
      const lastFortnightSunday = new Date(lastFortnightMonday)
      lastFortnightSunday.setDate(lastFortnightMonday.getDate() + 13)
      dateRange.value.startDate = toLocalDateString(lastFortnightMonday)
      dateRange.value.endDate = toLocalDateString(lastFortnightSunday)
      break
    }
    case 'lastMonth':
      dateRange.value.startDate = toLocalDateString(new Date(year, month - 1, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, month, 0))
      break
    case 'lastQuarter': {
      // Previous 3 months (rolling, not calendar quarter)
      const threeMonthsAgo = new Date(year, month - 3, 1)
      const lastDayOfLastMonth = new Date(year, month, 0)
      dateRange.value.startDate = toLocalDateString(threeMonthsAgo)
      dateRange.value.endDate = toLocalDateString(lastDayOfLastMonth)
      break
    }
  }
  loadData()
}

const loadData = async (includeDetails = false) => {
  if (!dateRange.value.startDate || !dateRange.value.endDate) return

  try {
    loading.value = true
    error.value = null

    const params: JobMovementParams = {
      start_date: dateRange.value.startDate,
      end_date: dateRange.value.endDate,
    }

    if (includeBaseline.value) {
      params.baseline_days = baselineDays.value
    }

    if (includeDetails) {
      params.include_details = true
    }

    const response = await jobMovementReportService.getJobMovementReport(params)
    reportData.value = response
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load job movement data'
    reportData.value = null
  } finally {
    loading.value = false
  }
}

const loadDataWithDetails = () => {
  loadData(true)
}

const exportToCsv = () => {
  if (!reportData.value) return

  const metrics = reportData.value.metrics
  const baseline = reportData.value.baseline

  const rows: string[][] = [
    ['Job Movement Report'],
    [`Period: ${reportData.value.period.start_date} to ${reportData.value.period.end_date}`],
    [],
    [
      'Metric',
      'Current Period',
      baseline ? 'Weekly Average' : '',
      baseline ? 'Baseline Total' : '',
    ],
    [
      'Draft Jobs Created',
      String(metrics.draft_jobs_created.count),
      baseline ? baseline.weekly_averages.draft_jobs_created.toFixed(1) : '',
      baseline ? String(baseline.totals.draft_jobs_created) : '',
    ],
    [
      'Quotes Submitted',
      String(metrics.quotes_submitted.count),
      baseline ? baseline.weekly_averages.quotes_submitted.toFixed(1) : '',
      baseline ? String(baseline.totals.quotes_submitted) : '',
    ],
    [
      'Quotes Accepted',
      String(metrics.quotes_accepted.count),
      baseline ? baseline.weekly_averages.quotes_accepted.toFixed(1) : '',
      baseline ? String(baseline.totals.quotes_accepted) : '',
    ],
    [
      'Jobs Won',
      String(metrics.jobs_won.count),
      baseline ? baseline.weekly_averages.jobs_won.toFixed(1) : '',
      baseline ? String(baseline.totals.jobs_won) : '',
    ],
    [],
    ['Rates'],
    [
      'Draft Conversion Rate',
      formatPercentage(metrics.draft_conversion_rate.rate),
      baseline ? formatPercentage(baseline.rates.draft_conversion_rate) : '',
    ],
    [
      'Quote Acceptance Rate',
      formatPercentage(metrics.quote_acceptance_rate.rate),
      baseline ? formatPercentage(baseline.rates.quote_acceptance_rate) : '',
    ],
    [
      'Quote Usage Rate',
      formatPercentage(metrics.workflow_paths.quote_usage_percent),
      baseline ? formatPercentage(baseline.rates.quote_usage_rate) : '',
    ],
    [],
    ['Workflow Paths'],
    ['Through Quotes', String(metrics.workflow_paths.through_quotes)],
    ['Direct (Skip Quotes)', String(metrics.workflow_paths.skip_quotes)],
    ['Still Draft', String(metrics.workflow_paths.still_draft)],
  ]

  const csvContent = rows.map((row) => row.join(',')).join('\n')

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  const url = URL.createObjectURL(blob)

  link.setAttribute('href', url)
  link.setAttribute(
    'download',
    `job-movement-${reportData.value.period.start_date}-to-${reportData.value.period.end_date}.csv`,
  )
  link.style.visibility = 'hidden'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

onMounted(() => {
  setDateRange('thisFortnight')
})
</script>
