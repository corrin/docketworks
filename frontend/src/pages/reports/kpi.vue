<template>
  <AppLayout>
    <div class="kpi-layout">
      <!-- Main Content -->
      <main class="kpi-main">
        <div class="w-full h-full flex flex-col overflow-hidden">
          <!-- Header Navigation -->
          <div
            class="hidden lg:flex items-center h-16 px-6 pt-4 bg-slate-900/80 border-b border-blue-500/10"
          >
            <div class="flex items-center space-x-4">
              <div class="flex items-center space-x-2">
                <BarChart3 class="h-8 w-8 text-blue-400" />
                <h1 class="text-white font-semibold text-lg">KPI Reports</h1>
              </div>
            </div>

            <div class="flex items-center space-x-2 mx-6">
              <MonthSelector
                :year="selectedYear"
                :month="selectedMonth"
                @update:year="
                  (year) => {
                    debugLog('Year changed to:', year)
                    selectedYear = year
                    fetchKPIData()
                  }
                "
                @update:month="
                  (month) => {
                    debugLog('Month changed to:', month)
                    selectedMonth = month
                    fetchKPIData()
                  }
                "
              />

              <Button
                variant="ghost"
                size="sm"
                @click="goToToday"
                class="text-white hover:bg-blue-500/20 ml-2"
              >
                Today
              </Button>
            </div>

            <div class="flex items-center space-x-2 ml-auto">
              <div class="text-xs text-blue-200 mr-4">
                <span class="font-semibold">Overview</span> View
              </div>

              <Button
                @click="exportData"
                size="sm"
                variant="default"
                class="bg-blue-600 hover:bg-blue-700 text-white border-blue-500"
              >
                <Download class="h-4 w-4 mr-1" />
                Export
              </Button>

              <Button
                @click="refreshData"
                variant="ghost"
                size="sm"
                :disabled="loading"
                class="text-white hover:bg-blue-500/20"
              >
                <RefreshCw :class="['h-4 w-4', { 'animate-spin': loading }]" />
              </Button>

              <Button
                @click="showSettingsModal = true"
                variant="ghost"
                size="sm"
                class="text-white hover:bg-blue-500/20"
              >
                <Settings class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <!-- Mobile Header -->
          <div class="block lg:hidden pt-4">
            <div
              class="flex items-center justify-between p-3 border-b border-blue-500/10 bg-slate-900/80"
            >
              <div class="flex items-center space-x-2">
                <BarChart3 class="h-6 w-6 text-blue-400" />
                <h1 class="text-white font-semibold">KPI Reports</h1>
              </div>
              <div class="text-xs text-blue-200">
                <span class="font-semibold">Overview</span>
              </div>
            </div>

            <div class="flex items-center justify-between p-3 bg-slate-900/80">
              <div class="flex items-center space-x-1">
                <MonthSelector
                  :year="selectedYear"
                  :month="selectedMonth"
                  @update:year="
                    (year) => {
                      selectedYear = year
                      fetchKPIData()
                    }
                  "
                  @update:month="
                    (month) => {
                      selectedMonth = month
                      fetchKPIData()
                    }
                  "
                />

                <Button
                  variant="ghost"
                  size="sm"
                  @click="goToToday"
                  class="h-7 text-xs px-2 text-white hover:bg-blue-500/20"
                >
                  Today
                </Button>
              </div>

              <div class="flex items-center space-x-1">
                <Button
                  @click="exportData"
                  size="sm"
                  variant="default"
                  class="h-7 text-xs px-2 bg-blue-600 hover:bg-blue-700 text-white border-blue-500"
                >
                  <Download class="h-3 w-3" />
                </Button>

                <Button
                  @click="refreshData"
                  variant="ghost"
                  size="sm"
                  :disabled="loading"
                  class="h-7 w-7 p-0 text-white hover:bg-blue-500/20"
                >
                  <RefreshCw :class="['h-3 w-3', { 'animate-spin': loading }]" />
                </Button>

                <Button
                  @click="showSettingsModal = true"
                  variant="ghost"
                  size="sm"
                  class="h-7 w-7 p-0 text-white hover:bg-blue-500/20"
                >
                  <Settings class="h-3 w-3" />
                </Button>
              </div>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto p-0">
            <div class="max-w-6xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-8">
              <!-- Overview Section -->
              <div class="space-y-6">
                <div class="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
                  <h1 class="text-2xl font-bold text-gray-900 mb-2">KPI Reports</h1>
                  <p class="text-gray-600">
                    Key Performance Indicators and business metrics dashboard
                  </p>
                </div>

                <!-- Loading State -->
                <div
                  v-if="kpiLoading"
                  class="bg-white p-6 rounded-lg shadow-sm border border-gray-200"
                >
                  <div class="text-center py-12">
                    <RefreshCw class="mx-auto h-8 w-8 text-gray-400 mb-4 animate-spin" />
                    <h3 class="text-lg font-medium text-gray-900 mb-2">Loading KPI Data...</h3>
                    <p class="text-gray-500">
                      Please wait while we fetch your performance metrics.
                    </p>
                  </div>
                </div>

                <!-- Error State -->
                <div
                  v-else-if="kpiError"
                  class="bg-white p-6 rounded-lg shadow-sm border border-red-200"
                >
                  <div class="text-center py-12">
                    <div
                      class="mx-auto h-12 w-12 bg-red-100 rounded-full flex items-center justify-center mb-4"
                    >
                      <span class="text-red-600 font-bold">!</span>
                    </div>
                    <h3 class="text-lg font-medium text-red-900 mb-2">Error Loading KPI Data</h3>
                    <p class="text-red-600 mb-4">{{ kpiError }}</p>
                    <Button
                      @click="fetchKPIData"
                      variant="outline"
                      class="border-red-300 text-red-600"
                    >
                      <RefreshCw class="h-4 w-4 mr-2" />
                      Retry
                    </Button>
                  </div>
                </div>

                <!-- KPI Dashboard -->
                <div v-else-if="kpiData" class="space-y-6">
                  <!-- KPI Metric Cards -->
                  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    <KPICard
                      title="Labour"
                      :value="`${formatHours(kpiData.monthly_totals.billable_hours)} billed`"
                      :subtitle="`${formatHours(kpiData.monthly_totals.total_hours)} wages`"
                      :percentage="avgBillableHoursDisplay"
                      description="Avg daily billable hours"
                      :trend="utilizationTrend"
                      :trend-direction="utilizationTrendDirection"
                      :variant="utilizationVariant"
                      :clickable="true"
                      @click="showLabourModal = true"
                    />
                    <KPICard
                      title="Materials"
                      :value="
                        formatCurrency(kpiData.monthly_totals.material_profit, { decimals: 0 })
                      "
                      :subtitle="[
                        `${formatCurrency(kpiData.monthly_totals.material_revenue, { decimals: 0 })} revenue`,
                        `${formatCurrency(kpiData.monthly_totals.material_cost, { decimals: 0 })} cost`,
                      ]"
                      :percentage="materialMargin"
                      description="margin"
                      :clickable="true"
                      @click="showMaterialsModal = true"
                    />
                    <KPICard
                      title="Adjustments"
                      :value="
                        formatCurrency(kpiData.monthly_totals.adjustment_profit, { decimals: 0 })
                      "
                      :subtitle="[
                        `${formatCurrency(kpiData.monthly_totals.adjustment_revenue, { decimals: 0 })} revenue`,
                        `${formatCurrency(kpiData.monthly_totals.adjustment_cost, { decimals: 0 })} cost`,
                      ]"
                      :percentage="adjustmentMargin"
                      description="margin"
                      :clickable="true"
                      @click="showMaterialsModal = true"
                    />
                    <KPICard
                      title="Profit"
                      :value="formatCurrency(kpiData.monthly_totals.net_profit, { decimals: 0 })"
                      :subtitle="[
                        `Rev: ${formatCurrency(kpiData.monthly_totals.total_revenue, { decimals: 0 })}`,
                        `GP: ${formatCurrency(kpiData.monthly_totals.gross_profit, { decimals: 0 })}`,
                      ]"
                      :percentage="profitMargin"
                      description="net margin"
                      :clickable="true"
                      @click="showProfitModal = true"
                    />
                  </div>

                  <!-- Calendar View -->
                  <KPICalendar
                    :calendar-data="kpiData.calendar_data"
                    :thresholds="kpiData.thresholds"
                    :year="kpiData.year"
                    :month="kpiData.month"
                    @day-click="handleDayClick"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>

    <!-- Day Details Modal -->
    <KPIDayDetailsModal
      :day-data="selectedDay"
      :is-open="showDayModal"
      @update:is-open="showDayModal = $event"
      @job-click="handleJobClick"
    />

    <!-- Labour Details Modal -->
    <KPILabourDetailsModal
      :monthly-data="kpiData?.monthly_totals || null"
      :calendar-data="kpiData?.calendar_data || null"
      :year="kpiData?.year || selectedYear"
      :month="kpiData?.month || selectedMonth"
      :is-open="showLabourModal"
      @update:is-open="showLabourModal = $event"
    />

    <!-- Materials Details Modal -->
    <KPIMaterialsDetailsModal
      :calendar-data="kpiData?.calendar_data || null"
      :year="kpiData?.year || selectedYear"
      :month="kpiData?.month || selectedMonth"
      :is-open="showMaterialsModal"
      @update:is-open="showMaterialsModal = $event"
    />

    <!-- Profit Details Modal -->
    <KPIProfitDetailsModal
      :monthly-data="kpiData?.monthly_totals || null"
      :thresholds="kpiData?.thresholds || null"
      :calendar-data="kpiData?.calendar_data || null"
      :year="kpiData?.year || selectedYear"
      :month="kpiData?.month || selectedMonth"
      :is-open="showProfitModal"
      @update:is-open="showProfitModal = $event"
    />
  </AppLayout>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import KPICard from '@/components/kpi/KPICard.vue'
import KPICalendar from '@/components/kpi/KPICalendar.vue'
import KPIDayDetailsModal from '@/components/kpi/KPIDayDetailsModal.vue'
import KPIProfitDetailsModal from '@/components/kpi/KPIProfitDetailsModal.vue'
import KPILabourDetailsModal from '@/components/kpi/KPILabourDetailsModal.vue'
import KPIMaterialsDetailsModal from '@/components/kpi/KPIMaterialsDetailsModal.vue'
import MonthSelector from '@/components/kpi/MonthSelector.vue'
import { kpiService } from '@/services/kpi.service'
import type { KPICalendarResponse, DayKPI } from '@/services/kpi.service'
import { BarChart3, Download, RefreshCw, Settings } from 'lucide-vue-next'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'

const router = useRouter()
const loading = ref(false)
const showSettingsModal = ref(false)
const showDayModal = ref(false)
const showProfitModal = ref(false)
const showLabourModal = ref(false)
const showMaterialsModal = ref(false)
const selectedDay = ref<DayKPI | null>(null)

const kpiData = ref<KPICalendarResponse | null>(null)
const kpiLoading = ref(false)
const kpiError = ref<string | null>(null)
const selectedYear = ref(new Date().getFullYear())
const selectedMonth = ref(new Date().getMonth() + 1)

function goToToday() {
  goToCurrentMonth()
}

function exportData() {
  debugLog('Exporting KPI data for overview')
}

function refreshData() {
  fetchKPIData()
}

async function fetchKPIData() {
  try {
    kpiLoading.value = true
    kpiError.value = null

    debugLog('Fetching KPI data for:', {
      year: selectedYear.value,
      month: selectedMonth.value,
    })

    const response = await kpiService.getAccountingKPICalendarData({
      year: selectedYear.value,
      month: selectedMonth.value,
    })

    debugLog('KPI data received:', {
      year: response.year,
      month: response.month,
      daysCount: Object.keys(response.calendar_data).length,
    })

    kpiData.value = response
  } catch (error) {
    debugLog('Error fetching KPI data:', error)
    kpiError.value = error instanceof Error ? error.message : 'Failed to load KPI data'
  } finally {
    kpiLoading.value = false
  }
}

const avgBillableHoursDisplay = computed(() => {
  if (!kpiData.value) return '0h'
  return formatHoursDisplay(kpiData.value.monthly_totals.avg_billable_hours_so_far)
})

const utilizationTrend = computed(() => {
  if (!kpiData.value) return ''
  return `${Math.round(kpiData.value.monthly_totals.billable_hours)}h`
})

const utilizationTrendDirection = computed(() => {
  if (!kpiData.value) return 'neutral'
  const avg = kpiData.value.monthly_totals.avg_billable_hours_so_far
  const { kpi_daily_billable_hours_green, kpi_daily_billable_hours_amber } =
    kpiData.value.thresholds
  if (avg >= kpi_daily_billable_hours_green) return 'up'
  if (avg >= kpi_daily_billable_hours_amber) return 'neutral'
  return 'down'
})

const utilizationVariant = computed(() => {
  if (!kpiData.value) return 'default'
  const avg = kpiData.value.monthly_totals.avg_billable_hours_so_far
  const { kpi_daily_billable_hours_green, kpi_daily_billable_hours_amber } =
    kpiData.value.thresholds
  if (avg >= kpi_daily_billable_hours_green) return 'success'
  if (avg >= kpi_daily_billable_hours_amber) return 'warning'
  return 'danger'
})

const materialMargin = computed(() => {
  if (!kpiData.value || kpiData.value.monthly_totals.material_revenue === 0) return '0%'
  const margin =
    (kpiData.value.monthly_totals.material_profit / kpiData.value.monthly_totals.material_revenue) *
    100
  return `${Math.round(margin)}%`
})

const adjustmentMargin = computed(() => {
  if (!kpiData.value || kpiData.value.monthly_totals.adjustment_revenue === 0) return '0%'
  const margin =
    (kpiData.value.monthly_totals.adjustment_profit /
      kpiData.value.monthly_totals.adjustment_revenue) *
    100
  return `${Math.round(margin)}%`
})

const profitMargin = computed(() => {
  if (!kpiData.value || kpiData.value.monthly_totals.total_revenue === 0) return '0%'
  const margin =
    (kpiData.value.monthly_totals.net_profit / kpiData.value.monthly_totals.total_revenue) * 100
  return `${Math.round(margin)}%`
})

function formatHours(hours: number): string {
  return kpiService.formatHours(hours)
}

function handleDayClick(day: DayKPI) {
  selectedDay.value = day
  showDayModal.value = true
}

function handleJobClick(jobId: string) {
  router.push(`/jobs/${jobId}`)
}

function goToCurrentMonth() {
  const now = new Date()
  selectedYear.value = now.getFullYear()
  selectedMonth.value = now.getMonth() + 1
  fetchKPIData()
}

onMounted(() => {
  fetchKPIData()
})
</script>

<style scoped>
.kpi-layout {
  display: flex;
  max-height: 100vh;
  height: auto;
  background: #f4f4f5;
  overflow: hidden;
}

.kpi-main {
  flex: 1 1 0;
  min-height: 0;
  height: auto;
  overflow-y: auto;
  background: #f4f4f5;
  padding: 0;
  min-width: 0;
  width: 100%;
}
</style>
