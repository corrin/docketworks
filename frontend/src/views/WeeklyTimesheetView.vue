<template>
  <AppLayout>
    <div class="flex flex-col flex-1 min-h-0">
      <div class="sticky top-0 z-20 bg-white backdrop-blur-md border-b border-gray-200 p-1">
        <div class="px-2 sm:px-3 lg:px-4 py-1 sm:py-1.5 lg:py-2">
          <div class="space-y-1 lg:space-y-0 pt-1 lg:pt-2">
            <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between">
              <div
                class="flex flex-col sm:flex-row sm:items-end sm:space-x-3 lg:space-x-4 text-center sm:text-left"
              >
                <h1 class="text-base sm:text-lg lg:text-2xl xl:text-3xl font-bold text-gray-900">
                  Weekly Timesheet Overview
                </h1>
                <div
                  class="flex items-center justify-center sm:justify-start space-x-1 lg:space-x-2 text-gray-600 mt-1 sm:mt-0"
                >
                  <Calendar class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
                  <span class="text-xs sm:text-sm lg:text-base">{{
                    formatDisplayDateRange()
                  }}</span>
                </div>
              </div>

              <div
                class="flex items-center justify-center sm:justify-end space-x-1 sm:space-x-2 lg:space-x-3 mt-1 sm:mt-0 lg:mt-2"
              >
                <div class="flex items-center space-x-1 lg:space-x-2">
                  <button
                    @click="togglePayrollMode(!payrollMode)"
                    :class="[
                      'relative inline-flex h-4 w-8 sm:h-5 sm:w-9 lg:h-6 lg:w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2',
                      payrollMode ? 'bg-blue-600' : 'bg-gray-200',
                    ]"
                  >
                    <span
                      :class="[
                        'inline-block h-2 w-2 sm:h-3 sm:w-3 lg:h-4 lg:w-4 transform rounded-full bg-white transition-transform',
                        payrollMode
                          ? 'translate-x-4 sm:translate-x-5 lg:translate-x-6'
                          : 'translate-x-0.5',
                      ]"
                    ></span>
                  </button>
                  <Label class="text-gray-700 text-xs sm:text-sm lg:text-base font-medium">
                    {{ payrollMode ? 'Loaded Wages' : 'Cash Wages' }}
                  </Label>
                </div>

                <Button
                  @click="openWeeklyMetricsModal"
                  variant="ghost"
                  size="sm"
                  class="text-gray-600 hover:bg-gray-100 text-xs sm:text-sm lg:text-base h-8 lg:h-10 px-2 lg:px-3"
                >
                  <BarChart3 class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5 sm:mr-2 lg:mr-2" />
                  <span class="hidden sm:inline">Job Metrics</span>
                </Button>

                <Button
                  @click="refreshData"
                  variant="ghost"
                  size="sm"
                  class="text-gray-600 hover:bg-gray-100 text-xs sm:text-sm lg:text-base h-8 lg:h-10 px-2 lg:px-3"
                  :disabled="loading"
                >
                  <RefreshCw
                    class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5 sm:mr-2 lg:mr-2"
                    :class="{ 'animate-spin': loading }"
                  />
                  <span class="hidden sm:inline">Refresh</span>
                </Button>

                <Button
                  @click="goToCurrentWeek"
                  variant="default"
                  size="sm"
                  class="bg-gray-600 hover:bg-gray-700 text-white border-gray-500 font-medium text-xs sm:text-sm lg:text-base h-8 lg:h-10 px-2 lg:px-4"
                >
                  <Home class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5 sm:mr-2 lg:mr-2" />
                  <span class="hidden sm:inline">This Week</span>
                </Button>
              </div>
            </div>

            <div class="flex items-center justify-center space-x-1 sm:space-x-2 lg:space-x-4">
              <Button
                @click="navigateWeek(-1)"
                variant="ghost"
                size="sm"
                class="text-gray-600 hover:bg-gray-100 px-1.5 sm:px-2 lg:px-3 h-8 lg:h-10"
              >
                <ChevronLeft class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
                <span class="hidden sm:inline ml-1 text-xs sm:text-sm lg:text-base">Previous</span>
              </Button>

              <Button
                @click="openWeekPicker"
                variant="ghost"
                size="sm"
                class="text-gray-600 hover:bg-gray-100 px-2 sm:px-3 lg:px-4 h-8 lg:h-10"
              >
                <CalendarDays class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5 mr-1 lg:mr-2" />
                <span class="text-xs sm:text-sm lg:text-base">Change Week</span>
              </Button>

              <Button
                @click="navigateWeek(1)"
                variant="ghost"
                size="sm"
                class="text-gray-600 hover:bg-gray-100 px-1.5 sm:px-2 lg:px-3 h-8 lg:h-10"
              >
                <span class="hidden sm:inline mr-1 text-xs sm:text-sm lg:text-base">Next</span>
                <ChevronRight class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div class="flex-1 p-1 sm:p-2 lg:p-3 space-y-2 sm:space-y-3 lg:space-y-4">
        <!-- Payroll Control Section -->
        <PayrollControlSection
          v-if="!loading && !error"
          :week-start-date="weekStartDate"
          :pay-run-status="payRunStatus"
          :payment-date="paymentDate"
          :xero-url="xeroUrl"
          :creating="creatingPayRun"
          :posting="postingAll"
          :posting-progress="postingProgress"
          :warning="payRunWarning"
          :payroll-error="payrollError"
          :refreshing="refreshingPayRuns"
          :post-success="postedAllToXero"
          :posting-blocked="!canPostCurrentWeek"
          :posting-blocked-reason="postingBlockedReason"
          :draft-week-start="draftWeekStart"
          @post-all-to-xero="handlePostAllToXero"
          @refresh-pay-runs="handleRefreshPayRuns"
          @dismiss-error="payrollError = null"
          @navigate-to-draft="handleNavigateToDraft"
        />

        <!-- Loading Spinner -->
        <div v-if="loading" class="flex-1 flex items-center justify-center bg-gray-50">
          <div class="text-center space-y-3 lg:space-y-4 p-6 lg:p-8">
            <div
              class="h-10 w-10 sm:h-12 sm:w-12 lg:h-14 lg:w-14 mx-auto rounded-full border-4 border-gray-300 border-t-gray-600 animate-spin"
            ></div>
            <p class="text-gray-600 text-base sm:text-lg lg:text-xl font-medium">
              Loading weekly timesheet data...
            </p>
          </div>
        </div>
        <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-3 sm:p-4 lg:p-6">
          <div class="flex items-start space-x-2 lg:space-x-3">
            <AlertCircle
              class="h-4 w-4 sm:h-5 sm:w-5 lg:h-6 lg:w-6 text-red-600 flex-shrink-0 mt-0.5"
            />
            <div class="flex-1">
              <h3 class="text-sm sm:text-base lg:text-lg font-semibold text-red-900">
                Error Loading Data
              </h3>
              <p class="text-red-700 text-xs sm:text-sm lg:text-base mt-1">{{ error }}</p>
              <Button @click="refreshData" class="mt-2 lg:mt-3" variant="outline" size="sm">
                <RefreshCw class="h-3 w-3 lg:h-4 lg:w-4 mr-2" />
                Try Again
              </Button>
            </div>
          </div>
        </div>

        <div v-else-if="weeklyData" class="space-y-2 lg:space-y-3">
          <div
            class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col"
          >
            <div class="overflow-x-auto">
              <table class="min-w-full divide-y divide-gray-200 table-fixed">
                <thead class="bg-gray-50">
                  <tr>
                    <th
                      class="w-48 px-1.5 py-1.5 lg:py-2 text-left text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Staff Member
                    </th>
                    <th
                      v-for="day in displayDays"
                      :key="day.date"
                      :class="[
                        'w-20 px-1 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium uppercase tracking-wider',
                        day.isWeekend ? 'bg-blue-50 text-blue-700' : 'text-gray-700',
                      ]"
                    >
                      <button
                        @click="goToDailyViewHeader(day.date)"
                        :class="[
                          'transition px-1 py-1 rounded focus:outline-none focus:ring-2 focus:ring-gray-400 text-xs w-full',
                          day.isWeekend
                            ? 'text-blue-700 hover:text-white hover:bg-blue-600'
                            : 'text-gray-700 hover:text-white hover:bg-gray-600',
                        ]"
                      >
                        <div class="flex flex-col items-center">
                          <span class="font-semibold">{{ day.name }}</span>
                          <span
                            class="text-xs normal-case"
                            :class="day.isWeekend ? 'text-blue-500' : 'text-gray-400'"
                          >
                            {{ day.short }}
                          </span>
                        </div>
                      </button>
                    </th>
                    <th
                      class="w-24 px-1.5 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Weekly Total
                    </th>
                    <th
                      class="w-28 px-1.5 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Billable Hours
                    </th>
                    <th
                      class="w-24 px-1.5 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                      title="Approximate cost based on wage rates - Xero has actual values"
                    >
                      Cost (approx)
                    </th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-100">
                  <PayrollStaffRow
                    v-for="staff in sortedStaffData"
                    :key="staff.staff_id"
                    :staff="staff"
                    :visible-indexes="displayDayIndexes"
                    :use-loaded-cost="payrollMode"
                  />
                </tbody>
                <tfoot class="bg-gray-100 border-t-2 border-gray-300">
                  <tr>
                    <td class="px-1.5 lg:px-2 py-2 lg:py-3">
                      <span class="text-sm lg:text-base font-bold text-gray-900">Total</span>
                    </td>
                    <td
                      v-for="idx in displayDayIndexes"
                      :key="`total-${idx}`"
                      class="px-1 py-2 lg:py-3 text-center"
                    >
                      <span class="text-sm lg:text-base font-bold text-gray-900">
                        {{ formatHours(getDailyTotalHours(idx)) }}
                      </span>
                    </td>
                    <td class="px-1.5 lg:px-2 py-2 lg:py-3 text-center">
                      <span class="text-sm lg:text-base font-bold text-gray-900">
                        {{ formatHours(getTotalHours()) }}
                      </span>
                    </td>
                    <td class="px-1.5 lg:px-2 py-2 lg:py-3 text-center">
                      <span class="text-sm lg:text-base font-bold text-gray-900">
                        {{ formatHours(getTotalBillableHours()) }}
                      </span>
                    </td>
                    <td class="px-1.5 lg:px-2 py-2 lg:py-3 text-center">
                      <span class="text-sm lg:text-base font-bold text-gray-900">
                        {{ formatCurrency(getTotalCost()) }}
                      </span>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        </div>
      </div>

      <WeeklyMetricsModal
        :is-open="showWeeklyMetricsModal"
        :weekly-data="weeklyData"
        :week-date="weekStartDate"
        @close="closeWeeklyMetricsModal"
      />

      <WeekPickerModal
        :is-open="showWeekPicker"
        :initial-week-start="weekStartDate"
        @close="closeWeekPicker"
        @week-selected="handleWeekSelect"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  Calendar,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Home,
  AlertCircle,
  BarChart3,
} from 'lucide-vue-next'

import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import Label from '@/components/ui/label/Label.vue'
import PayrollStaffRow from '@/components/timesheet/PayrollStaffRow.vue'
import WeeklyMetricsModal from '@/components/timesheet/WeeklyMetricsModal.vue'
import WeekPickerModal from '@/components/timesheet/WeekPickerModal.vue'
import PayrollControlSection from '@/components/timesheet/PayrollControlSection.vue'

import {
  dateService,
  createLocalDate,
  formatToLocalString,
  navigateWeek as navigateWeekDate,
} from '@/services/date.service'
import { fetchWeeklyOverview, formatHours } from '@/services/weekly-timesheet.service'
import { formatCurrency, humanizeErrorMessage } from '@/utils/string-formatting'
import {
  createPayRun,
  postStaffWeek,
  fetchAllPayRuns,
  refreshPayRuns,
  type PostStaffWeekCompleteEvent,
  type PayRunListItem,
} from '@/services/payroll.service'
import { schemas } from '@/api/generated/api'
import { debugLog } from '../utils/debug'
import { useTimesheetStore } from '@/stores/timesheet'
import { toast } from 'vue-sonner'
import { z } from 'zod'

type WeeklyTimesheetData = z.infer<typeof schemas.WeeklyTimesheetData>
type WeekDaySeed = { idx: number; dow: number; date: string }
type DisplayDay = WeekDaySeed & {
  name: string
  short: string
  isWeekend: boolean
}

const loading = ref(false)
const error = ref<string | null>(null)
const weeklyData = ref<WeeklyTimesheetData | null>(null)

const router = useRouter()
const route = useRoute()

function normalizeToWeekStart(dateInput: Date | string): Date {
  const { startDate } = dateService.getWeekRange(dateInput)
  return createLocalDate(startDate)
}

const initialWeekStart = route.query.week
  ? normalizeToWeekStart(route.query.week as string)
  : normalizeToWeekStart(new Date())
const selectedWeekStart = ref(initialWeekStart)
const weekStartDate = computed(() => dateService.getWeekRange(selectedWeekStart.value).startDate)

const payrollMode = ref(true)
const showWeeklyMetricsModal = ref(false)
const showWeekPicker = ref(false)

// All pay runs (for default week calculation, current week status, and posting restrictions)
const allPayRuns = ref<PayRunListItem[]>([])

// Payroll state
const payRunStatus = ref<string | null>(null)
const paymentDate = ref<string | null>(null)
const xeroUrl = ref<string | null>(null)
const creatingPayRun = ref(false)
const postingAll = ref(false)
const payRunWarning = ref<string | null>(null)
const payrollError = ref<string | null>(null)
const refreshingPayRuns = ref(false)
const postedAllToXero = ref(false)

// Posting progress state
const postingProgress = ref<{
  current: number
  total: number
  currentStaffName: string | null
  failedStaff: Array<{ staffName: string; error?: string }>
} | null>(null)

function resetPayRunState() {
  payRunStatus.value = null
  paymentDate.value = null
  xeroUrl.value = null
  payRunWarning.value = null
}

function loadPayRunForCurrentWeek() {
  if (!weekStartDate.value) {
    resetPayRunState()
    return
  }

  // Find pay run matching the current week from cached list
  const currentWeekStart = weekStartDate.value
  const payRun = allPayRuns.value.find((pr) => pr.period_start_date === currentWeekStart)

  if (payRun) {
    payRunStatus.value = payRun.pay_run_status
    paymentDate.value = payRun.payment_date
    xeroUrl.value = payRun.xero_url
    debugLog('Found pay run for current week:', payRun)
  } else {
    resetPayRunState()
    debugLog(`No pay run found for week starting ${currentWeekStart}`)
  }
}

// Load all pay runs (for default week calculation, current week status, and posting restrictions)
async function loadAllPayRuns(): Promise<PayRunListItem[]> {
  const result = await fetchAllPayRuns().catch((err) => {
    toast.error('Failed to load pay runs')
    throw err
  })
  allPayRuns.value = result.pay_runs
  debugLog('Loaded all pay runs:', result.pay_runs.length, 'items')
  return result.pay_runs
}

// Calculate the default week based on pay runs
function calculateDefaultWeek(payRuns: PayRunListItem[]): Date {
  // If query param exists, use that (user explicitly navigated to a week)
  if (route.query.week) {
    return normalizeToWeekStart(route.query.week as string)
  }

  // Find the latest Draft pay run (if any)
  const latestDraft = payRuns.find((pr) => pr.pay_run_status === 'Draft')
  if (latestDraft) {
    // Default to the week of the latest Draft
    return normalizeToWeekStart(latestDraft.period_start_date)
  }

  // Find the latest Posted pay run (if any)
  const latestPosted = payRuns.find((pr) => pr.pay_run_status === 'Posted')
  if (latestPosted) {
    // Default to week AFTER the latest Posted
    const endDate = createLocalDate(latestPosted.period_end_date)
    endDate.setDate(endDate.getDate() + 1)
    return normalizeToWeekStart(endDate)
  }

  // Default to current week
  return normalizeToWeekStart(new Date())
}

// Use timesheet store for weekend functionality
const timesheetStore = useTimesheetStore()
const weekendEnabled = computed(() => {
  timesheetStore.initializeFeatureFlags()
  return import.meta.env.VITE_WEEKEND_TIMESHEETS_ENABLED === 'true'
})

const visibleDayIndexes = computed<number[]>(() => {
  if (!weeklyData.value?.week_days) return []
  const weekDays = weeklyData.value.week_days
  const raw: WeekDaySeed[] = weekDays.map((day, idx) => ({
    idx,
    dow: createLocalDate(day).getDay(),
    date: day,
  }))

  if (!weekendEnabled.value) {
    return raw
      .filter((seed) => seed.dow >= 1 && seed.dow <= 5)
      .sort((a, b) => a.dow - b.dow)
      .map((seed) => seed.idx)
  }

  return raw.map((seed) => seed.idx)
})

// Sort staff data alphabetically by first name for consistent display
const sortedStaffData = computed(() => {
  if (!weeklyData.value?.staff_data) return []

  return [...weeklyData.value.staff_data].sort((a, b) => a.name.localeCompare(b.name))
})
const displayDays = computed<DisplayDay[]>(() => {
  if (!weeklyData.value?.week_days || !Array.isArray(weeklyData.value.week_days)) {
    debugLog('No valid weekly data available for displayDays computation')
    return []
  }

  const weekDays = weeklyData.value.week_days
  return visibleDayIndexes.value
    .map((idx) => {
      const dayValue = weekDays[idx]
      if (!dayValue) {
        return null
      }

      const date = createLocalDate(dayValue)
      const dow = date.getDay()
      return {
        idx,
        date: dayValue,
        name: dateService.getDayName(dayValue, true),
        short: dateService.getDayNumber(dayValue),
        dow,
        isWeekend: dow === 0 || dow === 6,
      }
    })
    .filter((entry): entry is DisplayDay => entry !== null)
})

const displayDayIndexes = computed<number[]>(() => displayDays.value.map((day) => day.idx))

// Find the latest Posted pay run from the list
const latestPostedPayRun = computed(() => {
  return allPayRuns.value.find((pr) => pr.pay_run_status === 'Posted') ?? null
})

// Posting restrictions based on latest posted pay run
const canPostCurrentWeek = computed(() => {
  // If no posted pay runs exist, posting is allowed
  if (!latestPostedPayRun.value) {
    return true
  }

  // Get the end date of the currently selected week
  const currentWeekEnd = dateService.getWeekRange(selectedWeekStart.value).endDate

  // Can post if current week ends AFTER the latest posted period
  return currentWeekEnd > latestPostedPayRun.value.period_end_date
})

const postingBlockedReason = computed(() => {
  if (canPostCurrentWeek.value) return null
  if (!latestPostedPayRun.value?.period_end_date) return null

  const latestEndDate = latestPostedPayRun.value.period_end_date
  const formattedDate = dateService.formatDisplayDate(latestEndDate)
  return `Cannot post: A pay run has already been posted for the week ending ${formattedDate}. You can only post pay runs for weeks after this date.`
})

// Get the week start date of an existing draft (if any) - component derives all draft logic from this
const draftWeekStart = computed(() => {
  const draft = allPayRuns.value.find((pr) => pr.pay_run_status === 'Draft')
  return draft?.period_start_date ?? null
})

watch(
  () => selectedWeekStart.value.getTime(),
  () => {
    void loadPayRunForCurrentWeek()
  },
  { immediate: true },
)

// Format the header's date range
function formatDisplayDateRange(): string {
  if (!weeklyData.value) return ''
  return dateService.formatDateRange(weeklyData.value.start_date, weeklyData.value.end_date)
}

// Total row helper functions
function getDailyTotalHours(dayIndex: number): number {
  if (!weeklyData.value?.staff_data) return 0
  return weeklyData.value.staff_data.reduce((sum, staff) => {
    return sum + (staff.weekly_hours[dayIndex]?.hours ?? 0)
  }, 0)
}

function getTotalHours(): number {
  if (!weeklyData.value?.staff_data) return 0
  return weeklyData.value.staff_data.reduce((sum, staff) => sum + staff.total_hours, 0)
}

function getTotalBillableHours(): number {
  if (!weeklyData.value?.staff_data) return 0
  return weeklyData.value.staff_data.reduce((sum, staff) => sum + staff.total_billable_hours, 0)
}

function getTotalCost(): number {
  if (!weeklyData.value?.staff_data) return 0
  return weeklyData.value.staff_data.reduce((sum, staff) => {
    return sum + (payrollMode.value ? staff.weekly_cost : staff.weekly_base_cost)
  }, 0)
}

// Core data loader with enhanced error handling
async function loadData(): Promise<void> {
  console.log('[WeeklyTimesheet] loadData: starting')
  loading.value = true
  error.value = null
  postedAllToXero.value = false

  // Payroll state (pay runs) is refreshed separately via loadPayRunForCurrentWeek

  try {
    const { startDate } = dateService.getWeekRange(selectedWeekStart.value)

    // Fetch weekly data (includes all payroll breakdown regardless of mode)
    console.time('[WeeklyTimesheet] fetchWeeklyOverview API call')
    weeklyData.value = await fetchWeeklyOverview(startDate)
    console.timeEnd('[WeeklyTimesheet] fetchWeeklyOverview API call')
    console.log(
      '[WeeklyTimesheet] loadData: data received, staff count:',
      weeklyData.value?.staff_data?.length,
    )

    // Validate response structure
    if (!weeklyData.value?.week_days || !Array.isArray(weeklyData.value.week_days)) {
      throw new Error('Invalid response structure: missing or invalid week_days array')
    }

    // Log successful load with weekend information
    const dayCount = weeklyData.value.week_days.length
    const expectedDays = weekendEnabled.value ? 7 : 5
    debugLog(`Weekly data loaded successfully: ${dayCount} days (expected: ${expectedDays})`)

    // Warn if day count doesn't match expectation
    if (dayCount !== expectedDays) {
      console.warn(
        `Day count mismatch: received ${dayCount} days, expected ${expectedDays} (weekend: ${weekendEnabled.value})`,
      )
    }
  } catch (err: unknown) {
    const rawMessage = err instanceof Error ? err.message : 'Unknown error'
    const errorMessage = humanizeErrorMessage(rawMessage)
    error.value = `Failed to load weekly timesheet data. Please try again. ${errorMessage}`

    debugLog('Error while loading weekly timesheet data:', {
      error: err,
      payrollMode: payrollMode.value,
      weekendEnabled: weekendEnabled.value,
      selectedWeekStart: selectedWeekStart.value,
    })

    // Provide fallback: show empty state instead of crashing
    weeklyData.value = null
  } finally {
    loading.value = false
  }
}

// Helpers
function refreshData() {
  loadData()
}
function navigateWeek(direction: number) {
  const newDate = navigateWeekDate(formatToLocalString(selectedWeekStart.value), direction)
  selectedWeekStart.value = createLocalDate(newDate)
  router.push({ query: { week: weekStartDate.value } })
  loadData()
}
function goToCurrentWeek() {
  selectedWeekStart.value = createLocalDate(dateService.getCurrentWeekStart())
  router.push({ query: { week: weekStartDate.value } })
  loadData()
}
function togglePayrollMode(checked: boolean) {
  payrollMode.value = checked
  debugLog(`Switched to ${payrollMode.value ? 'Loaded Wages' : 'Cash Wages'}`)
}
function goToDailyViewHeader(date: string) {
  router.push({ name: 'timesheet-daily', query: { date } })
}
function openWeeklyMetricsModal() {
  showWeeklyMetricsModal.value = true
}
function closeWeeklyMetricsModal() {
  showWeeklyMetricsModal.value = false
}
function openWeekPicker() {
  showWeekPicker.value = true
}
function closeWeekPicker() {
  showWeekPicker.value = false
}
function handleWeekSelect(date: string) {
  selectedWeekStart.value = createLocalDate(date)
  router.push({ query: { week: weekStartDate.value } })
  loadData()
  closeWeekPicker()
}

// Payroll functions
async function handleCreatePayRun() {
  creatingPayRun.value = true
  payrollError.value = null
  try {
    const result = await createPayRun(weekStartDate.value)

    payRunStatus.value = result.status
    paymentDate.value = result.payment_date
    const xeroUrlRaw = (result as { xero_url?: unknown }).xero_url
    const xeroUrlValue: string | null = typeof xeroUrlRaw === 'string' ? xeroUrlRaw : null
    xeroUrl.value = xeroUrlValue

    toast.success('Pay run created successfully', {
      description: `Payment date: ${result.payment_date}`,
    })

    debugLog('Pay run created:', result)
  } catch (err: unknown) {
    console.error('Create pay run failed:', err)

    payrollError.value = 'Failed to create pay run. Please try again or contact Corrin.'
    toast.error('Failed to create pay run', {
      description: 'Something went wrong. Please try again or contact Corrin.',
    })
  } finally {
    creatingPayRun.value = false
  }
}

async function handleRefreshPayRuns() {
  refreshingPayRuns.value = true
  payrollError.value = null
  try {
    const result = await refreshPayRuns()
    toast.success('Pay runs refreshed', {
      description: `Fetched ${result.fetched}, created ${result.created}, updated ${result.updated}`,
    })
    debugLog('Pay runs synced from Xero:', result)
    // Reload all pay runs and update current week status
    await loadAllPayRuns()
    loadPayRunForCurrentWeek()
  } catch (err: unknown) {
    console.error('Refresh pay runs failed:', err)

    payrollError.value = 'Failed to refresh pay runs. Please try again or contact Corrin.'
    toast.error('Failed to refresh pay runs', {
      description: 'Something went wrong. Please try again or contact Corrin.',
    })
  } finally {
    refreshingPayRuns.value = false
  }
}

function handleNavigateToDraft() {
  if (draftWeekStart.value) {
    selectedWeekStart.value = createLocalDate(draftWeekStart.value)
    router.push({ query: { week: draftWeekStart.value } })
    loadData()
  }
}

async function handlePostAllToXero() {
  if (!weeklyData.value) return

  postingAll.value = true
  payrollError.value = null
  postingProgress.value = null

  const staffList = weeklyData.value.staff_data || []
  if (!staffList.length) {
    postingAll.value = false
    toast.error('No staff data available', {
      description: 'Refresh the week before posting to Xero.',
    })
    debugLog('Post all aborted: no staff_data in weekly payload', weeklyData.value)
    return
  }

  const weekStart = weekStartDate.value || weeklyData.value?.start_date || null

  if (!weekStart) {
    postingAll.value = false
    toast.error('Missing week start', {
      description: 'Unable to determine the selected week. Please refresh and try again.',
    })
    debugLog('Post all aborted: missing week start', {
      selectedWeekStart: selectedWeekStart.value,
      weeklyData: weeklyData.value,
    })
    return
  }

  // Collect all valid staff IDs
  const staffIds: string[] = []
  for (const staff of staffList) {
    if (staff.staff_id) {
      staffIds.push(staff.staff_id)
    } else {
      debugLog('Skipping staff with missing identifier', staff)
    }
  }

  if (!staffIds.length) {
    postingAll.value = false
    toast.error('No staff IDs available', {
      description: 'Unable to find staff identifiers for payroll posting. Please refresh.',
    })
    debugLog('Post all aborted: no staff IDs in payload', staffList)
    return
  }

  // Track failed and skipped staff for reporting
  const failedStaff: Array<{ staffName: string; error?: string }> = []
  const skippedInactiveWithEntries: string[] = []

  try {
    const result = await postStaffWeek(staffIds, weekStart, {
      onStart: (event) => {
        postingProgress.value = {
          current: 0,
          total: event.total,
          currentStaffName: null,
          failedStaff: [],
        }
        debugLog('Starting batch post:', event)
      },
      onProgress: (event) => {
        if (postingProgress.value) {
          postingProgress.value = {
            ...postingProgress.value,
            current: event.current,
            currentStaffName: event.staff_name,
          }
        }
        debugLog('Progress:', event)
      },
      onComplete: (event: PostStaffWeekCompleteEvent) => {
        if (!event.success) {
          const errorMsg = event.errors?.join('; ') || 'Unknown error'
          failedStaff.push({
            staffName: event.staff_name,
            error: errorMsg,
          })
          if (postingProgress.value) {
            postingProgress.value = {
              ...postingProgress.value,
              failedStaff: [...failedStaff],
            }
          }
          // Log detailed error to console for debugging
          console.error(`Failed to post timesheet for ${event.staff_name}:`, errorMsg)
        } else if (event.skipped) {
          if (event.has_entries) {
            // Track inactive staff with entries that were skipped
            skippedInactiveWithEntries.push(event.staff_name)
            console.warn(`Skipped inactive staff with entries: ${event.staff_name}`)
          } else {
            debugLog(`Skipped inactive staff (no entries): ${event.staff_name}`)
          }
        }
        debugLog('Complete:', event)
      },
      onDone: (event) => {
        debugLog('Batch post done:', event)
      },
    })

    const totalPosted = result.successful + result.failed
    if (result.failed > 0) {
      const failedNames = failedStaff.map((s) => s.staffName).join(', ')
      payrollError.value = `Failed to post ${result.failed} of ${totalPosted} staff members to Xero: ${failedNames}`
      toast.error('Some staff failed to post', {
        description: failedNames,
      })
      postedAllToXero.value = false
    } else {
      toast.success('All staff posted successfully', {
        description: `${result.successful} staff members posted to Xero. Creating pay run...`,
      })
      postedAllToXero.value = true

      // Automatically create the pay run after successful posting
      await handleCreatePayRun()
    }

    // Warn about inactive staff with entries that were skipped
    if (skippedInactiveWithEntries.length > 0) {
      const names = skippedInactiveWithEntries.join(', ')
      toast.warning('Inactive staff with time entries', {
        description: `${names} - hours not posted to Xero`,
      })
    }
  } catch (err: unknown) {
    console.error('Payroll post failed:', err)

    payrollError.value = 'Unable to post to Xero. Please try again or contact Corrin.'
    toast.error('Unable to post to Xero', {
      description: 'Something went wrong. Please try again or contact Corrin.',
    })
    postedAllToXero.value = false
  } finally {
    postingAll.value = false
    postingProgress.value = null
  }
}

onMounted(async () => {
  console.time('[WeeklyTimesheet] total mount')

  // If no week param, sync pay runs from Xero first (ensures fresh data for default week)
  if (!route.query.week) {
    try {
      console.time('[WeeklyTimesheet] refreshPayRuns')
      await refreshPayRuns()
      console.timeEnd('[WeeklyTimesheet] refreshPayRuns')
      debugLog('Pay runs synced from Xero on initial load')
    } catch (err) {
      console.error('Failed to sync pay runs from Xero:', err)
      toast.error('Failed to sync pay runs from Xero')
    }
  }

  // Fetch all pay runs (needed for default week calculation and restrictions)
  console.time('[WeeklyTimesheet] loadAllPayRuns')
  const payRuns = await loadAllPayRuns()
  console.timeEnd('[WeeklyTimesheet] loadAllPayRuns')

  // If no query param, set the default week based on pay runs
  if (!route.query.week) {
    console.time('[WeeklyTimesheet] calculateDefaultWeek')
    const defaultWeek = calculateDefaultWeek(payRuns)
    console.timeEnd('[WeeklyTimesheet] calculateDefaultWeek')
    selectedWeekStart.value = defaultWeek
    // Update URL to reflect the calculated week
    router.replace({ query: { week: dateService.getWeekRange(defaultWeek).startDate } })
  }

  // Load current week's pay run status from cached list
  console.time('[WeeklyTimesheet] loadPayRunForCurrentWeek')
  loadPayRunForCurrentWeek()
  console.timeEnd('[WeeklyTimesheet] loadPayRunForCurrentWeek')

  // Then load the timesheet data
  console.time('[WeeklyTimesheet] loadData')
  await loadData()
  console.timeEnd('[WeeklyTimesheet] loadData')

  console.timeEnd('[WeeklyTimesheet] total mount')
})
</script>

<style scoped>
.group:hover .transform {
  transform: scale(1.05);
}

tbody tr:hover {
  background-color: rgba(249, 250, 251, 0.5);
  transition: background-color 0.15s ease-in-out;
}

@keyframes pulse-glow {
  0%,
  100% {
    opacity: 1;
    box-shadow: 0 0 0 0 rgba(147, 51, 234, 0.7);
  }

  50% {
    opacity: 0.5;
    box-shadow: 0 0 0 10px rgba(147, 51, 234, 0);
  }
}

.animate-pulse-glow {
  animation: pulse-glow 2s infinite;
}

.text-amber-600 {
  color: #d97706;
}

.text-red-600 {
  color: #dc2626;
}

.text-blue-600 {
  color: #2563eb;
}

.text-green-600 {
  color: #059669;
}

.text-orange-600 {
  color: #ea580c;
}

.bg-gray-50 {
  background-color: #f9fafb;
}

.bg-green-50 {
  background-color: #f0fdf4;
}

.bg-orange-100 {
  background-color: #fed7aa;
}

.text-orange-800 {
  color: #9a3412;
}
</style>
