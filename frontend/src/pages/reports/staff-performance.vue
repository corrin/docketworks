<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <Users class="w-8 h-8 text-indigo-400" />
              Staff Performance Report
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportToCsv"
                :disabled="loading || !staffData.length"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="default"
                @click="refreshData"
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
                  @change="loadData"
                />
              </div>
              <div class="flex items-center gap-2">
                <label for="end-date" class="text-sm font-medium text-gray-700"> End Date: </label>
                <input
                  id="end-date"
                  v-model="dateRange.endDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="loadData"
                />
              </div>
              <div class="flex gap-2">
                <Button variant="outline" size="sm" @click="setDateRange('thisMonth')">
                  This Month
                </Button>
                <Button variant="outline" size="sm" @click="setDateRange('lastMonth')">
                  Last Month
                </Button>
                <Button variant="outline" size="sm" @click="setDateRange('thisQuarter')">
                  This Quarter
                </Button>
              </div>
            </div>
          </div>

          <!-- Team Averages Summary -->
          <div v-if="teamAverages" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Team Billable %</p>
                  <p class="text-2xl font-bold text-gray-900">
                    {{ formatPercentage(teamAverages.billable_percentage) }}
                  </p>
                </div>
                <Clock class="h-8 w-8 text-blue-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Revenue/Hour</p>
                  <p class="text-2xl font-bold text-gray-900">
                    {{ formatCurrency(teamAverages.revenue_per_hour) }}
                  </p>
                </div>
                <DollarSign class="h-8 w-8 text-green-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Profit/Hour</p>
                  <p class="text-2xl font-bold text-gray-900">
                    {{ formatCurrency(teamAverages.profit_per_hour) }}
                  </p>
                </div>
                <TrendingUp class="h-8 w-8 text-purple-500" />
              </div>
            </div>

            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center justify-between">
                <div>
                  <p class="text-sm font-medium text-gray-600">Total Staff</p>
                  <p class="text-2xl font-bold text-gray-900">
                    {{ staffData.length }}
                  </p>
                </div>
                <Users class="h-8 w-8 text-orange-500" />
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div v-if="loading" class="flex items-center justify-center py-12">
            <RefreshCw class="h-8 w-8 animate-spin text-indigo-500" />
            <span class="ml-2 text-lg text-gray-600">Loading staff performance data...</span>
          </div>

          <!-- Error State -->
          <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="flex items-center">
              <AlertCircle class="h-5 w-5 text-red-400 mr-2" />
              <span class="text-red-800">{{ error }}</span>
            </div>
          </div>

          <!-- Staff Performance Table -->
          <div
            v-else-if="staffData.length > 0"
            class="bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden"
          >
            <div class="px-4 py-5 sm:p-6">
              <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                  <thead class="bg-gray-50">
                    <tr>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Staff Member
                      </th>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Total Hours
                      </th>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Billable %
                      </th>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Revenue/Hour
                      </th>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Profit/Hour
                      </th>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Jobs
                      </th>
                      <th
                        class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                      >
                        Total Revenue
                      </th>
                    </tr>
                  </thead>
                  <tbody class="bg-white divide-y divide-gray-200">
                    <tr v-for="staff in staffData" :key="staff.staff_id" class="hover:bg-gray-50">
                      <td class="px-6 py-4 whitespace-nowrap">
                        <div class="flex items-center">
                          <div>
                            <div class="text-sm font-medium text-gray-900">{{ staff.name }}</div>
                            <div v-if="getProblems(staff).length > 0" class="text-xs text-red-600">
                              {{ getProblems(staff).join(', ') }}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {{ formatHours(staff.total_hours) }}
                        <div class="text-xs text-gray-500">
                          ({{ formatHours(staff.billable_hours) }} billable)
                        </div>
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap">
                        <span
                          class="inline-flex px-2 py-1 text-xs font-semibold rounded-full"
                          :class="
                            getPerformanceBadgeClass(
                              staff.billable_percentage,
                              teamAverages?.billable_percentage,
                            )
                          "
                        >
                          {{ formatPercentage(staff.billable_percentage) }}
                        </span>
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap">
                        <span
                          class="inline-flex px-2 py-1 text-xs font-semibold rounded-full"
                          :class="
                            getPerformanceBadgeClass(
                              staff.revenue_per_hour,
                              teamAverages?.revenue_per_hour,
                            )
                          "
                        >
                          {{ formatCurrency(staff.revenue_per_hour) }}
                        </span>
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap">
                        <span
                          class="inline-flex px-2 py-1 text-xs font-semibold rounded-full"
                          :class="
                            getPerformanceBadgeClass(
                              staff.profit_per_hour,
                              teamAverages?.profit_per_hour,
                            )
                          "
                        >
                          {{ formatCurrency(staff.profit_per_hour) }}
                        </span>
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {{ staff.jobs_worked }}
                      </td>
                      <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {{ formatCurrency(staff.total_revenue) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <!-- Empty State -->
          <div v-else class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center">
            <Users class="mx-auto h-12 w-12 text-gray-400" />
            <h3 class="mt-2 text-sm font-medium text-gray-900">No staff performance data</h3>
            <p class="mt-1 text-sm text-gray-500">
              No performance data found for the selected date range.
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
  Users,
  Download,
  RefreshCw,
  Clock,
  DollarSign,
  TrendingUp,
  AlertCircle,
} from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { staffPerformanceReportService } from '@/services/staff-performance-report.service'
import { formatCurrency } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import type {
  StaffPerformanceData,
  TeamAverages,
  StaffPerformanceReportParams,
} from '@/types/staff-performance.types'

const loading = ref(false)
const error = ref<string | null>(null)
const staffData = ref<StaffPerformanceData[]>([])
const teamAverages = ref<TeamAverages | null>(null)

const dateRange = ref({
  startDate: '',
  endDate: '',
})

const formatHours = (hours: number): string => {
  return staffPerformanceReportService.formatHours(hours)
}

const formatPercentage = (percentage: number): string => {
  return staffPerformanceReportService.formatPercentage(percentage)
}

const getProblems = (staff: StaffPerformanceData): string[] => {
  if (!teamAverages.value) return []
  return staffPerformanceReportService.detectProblems(staff, teamAverages.value)
}

const getPerformanceBadgeClass = (staffValue: number, teamValue?: number): string => {
  if (!teamValue) return 'bg-gray-100 text-gray-800'

  const comparison = staffPerformanceReportService.getPerformanceComparison(staffValue, teamValue)
  const variant = staffPerformanceReportService.getPerformanceVariant(comparison.status)

  switch (variant) {
    case 'success':
      return 'bg-green-100 text-green-800'
    case 'warning':
      return 'bg-yellow-100 text-yellow-800'
    case 'danger':
      return 'bg-red-100 text-red-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}

const setDateRange = (period: 'thisMonth' | 'lastMonth' | 'thisQuarter') => {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()

  switch (period) {
    case 'thisMonth':
      dateRange.value.startDate = toLocalDateString(new Date(year, month, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, month + 1, 0))
      break
    case 'lastMonth':
      dateRange.value.startDate = toLocalDateString(new Date(year, month - 1, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, month, 0))
      break
    case 'thisQuarter':
      const quarterStart = Math.floor(month / 3) * 3
      dateRange.value.startDate = toLocalDateString(new Date(year, quarterStart, 1))
      dateRange.value.endDate = toLocalDateString(new Date(year, quarterStart + 3, 0))
      break
  }
  loadData()
}

const loadData = async () => {
  if (!dateRange.value.startDate || !dateRange.value.endDate) return

  try {
    loading.value = true
    error.value = null

    const params: StaffPerformanceReportParams = {
      start_date: dateRange.value.startDate,
      end_date: dateRange.value.endDate,
    }

    const response = await staffPerformanceReportService.getStaffPerformanceSummary(params)
    staffData.value = response.staff
    teamAverages.value = response.team_averages
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load staff performance data'
    staffData.value = []
    teamAverages.value = null
  } finally {
    loading.value = false
  }
}

const refreshData = () => {
  loadData()
}

const exportToCsv = () => {
  if (!teamAverages.value || staffData.value.length === 0) return

  const dateRangeStr = `${dateRange.value.startDate} to ${dateRange.value.endDate}`
  staffPerformanceReportService.exportToFile(staffData.value, teamAverages.value, dateRangeStr)
}

onMounted(() => {
  // Set default to this month
  setDateRange('thisMonth')
})
</script>
