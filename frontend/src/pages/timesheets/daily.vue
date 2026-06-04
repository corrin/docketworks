<template>
  <AppLayout>
    <div class="flex flex-col flex-1 min-h-0">
      <div class="sticky top-0 z-20 bg-white backdrop-blur-md border-b border-gray-200">
        <div class="px-2 sm:px-3 lg:px-4 py-1 sm:py-2 lg:py-3">
          <div class="flex items-center justify-center pt-1 lg:pt-2">
            <div class="flex items-center space-x-4 sm:space-x-6 lg:space-x-8">
              <!-- Left: Title and Date -->
              <div class="flex items-center space-x-3 lg:space-x-4">
                <h1 class="text-base sm:text-lg lg:text-2xl xl:text-3xl font-bold text-gray-900">
                  Daily Timesheet
                </h1>
                <div class="flex items-center space-x-1 lg:space-x-2 text-gray-600">
                  <Calendar class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
                  <span class="text-xs sm:text-sm lg:text-base">{{
                    formatDisplayDate(selectedDate)
                  }}</span>
                </div>
              </div>

              <!-- Right: Action Buttons -->
              <div class="flex items-center space-x-1 sm:space-x-2 lg:space-x-3">
                <Button
                  @click="openMetricsModal"
                  variant="ghost"
                  size="sm"
                  class="text-gray-600 hover:bg-gray-100 text-xs sm:text-sm lg:text-base h-8 lg:h-10 px-2 lg:px-3"
                >
                  <BarChart3 class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5 sm:mr-2 lg:mr-2" />
                  <span class="hidden sm:inline">Metrics</span>
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
                  @click="goToToday"
                  variant="default"
                  size="sm"
                  class="bg-gray-600 hover:bg-gray-700 text-white border-gray-500 font-medium text-xs sm:text-sm lg:text-base h-8 lg:h-10 px-3 lg:px-4"
                >
                  <Home class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5 sm:mr-2 lg:mr-2" />
                  <span class="hidden sm:inline">Today</span>
                </Button>
              </div>
            </div>
          </div>

          <!-- Navigation Row -->
          <div
            class="flex items-center justify-center space-x-1 sm:space-x-2 lg:space-x-4 mt-2 lg:mt-3"
          >
            <Button
              @click="navigateDate(-1)"
              variant="ghost"
              size="sm"
              class="text-gray-600 hover:bg-gray-100 px-1.5 sm:px-2 lg:px-3 h-8 lg:h-10"
            >
              <ChevronLeft class="h-3 w-3 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
              <span class="hidden sm:inline ml-1 text-xs sm:text-sm lg:text-base">Previous</span>
            </Button>

            <div class="flex items-center space-x-1 lg:space-x-2">
              <input
                type="date"
                v-model="selectedDate"
                @change="loadData"
                class="px-1.5 sm:px-2 lg:px-3 py-1 sm:py-1.5 lg:py-2 bg-white border border-gray-300 rounded-md text-gray-900 text-xs sm:text-sm lg:text-base focus:outline-none focus:ring-2 focus:ring-gray-500 w-28 sm:w-32 lg:w-40 h-8 lg:h-10"
              />
            </div>

            <Button
              @click="navigateDate(1)"
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

      <div class="p-1 sm:p-2 lg:p-3 space-y-2 sm:space-y-3 lg:space-y-4 flex-1 min-h-0 pb-6">
        <div v-if="loading" class="flex items-center justify-center py-6 sm:py-8 lg:py-10">
          <div class="text-center">
            <div
              class="animate-spin rounded-full h-6 w-6 sm:h-8 sm:w-8 lg:h-10 lg:w-10 border-b-2 border-gray-600 mx-auto mb-3 lg:mb-4"
            ></div>
            <p class="text-gray-600 text-sm sm:text-base lg:text-lg">Loading timesheet data...</p>
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

        <div v-else-if="summary" class="space-y-2 lg:space-y-3">
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
                      class="w-24 px-1.5 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Hours
                    </th>
                    <th
                      class="w-28 px-1.5 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Status
                    </th>
                    <th
                      class="w-32 px-1.5 py-1.5 lg:py-2 text-center text-xs sm:text-sm lg:text-base font-medium text-gray-500 uppercase tracking-wider"
                    >
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-100">
                  <StaffRow
                    v-for="staff in summary.staff_data"
                    :key="staff.staff_id"
                    :staff="staff"
                    :date="selectedDate"
                    @view-details="openStaffModal"
                  />
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      <StaffDetailModal
        v-if="selectedStaff"
        :staff="selectedStaff"
        :date="selectedDate"
        :open="showStaffModal"
        @close="closeStaffModal"
      />

      <MetricsModal
        v-if="summary"
        :summary="summary"
        :open="showMetricsModal"
        @close="closeMetricsModal"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Home,
  AlertCircle,
  BarChart3,
} from 'lucide-vue-next'

import StaffRow from '@/components/timesheet/StaffRow.vue'
import StaffDetailModal from '@/components/timesheet/StaffDetailModal.vue'
import MetricsModal from '@/components/timesheet/MetricsModal.vue'

import {
  getDailyTimesheetSummary,
  type DailyTimesheetSummary,
  type StaffDailyData,
} from '@/services/daily-timesheet.service'
import { dateService, today, navigateDay } from '@/services/date.service'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const error = ref<string | null>(null)
const summary = ref<DailyTimesheetSummary | null>(null)

const initialDate = (route.query.date as string) || today()
const selectedDate = ref(initialDate)

const selectedStaff = ref<StaffDailyData | null>(null)
const showStaffModal = ref(false)
const showMetricsModal = ref(false)

debugLog('DailyTimesheetView URL params:', { date: route.query.date })
debugLog('Using initial date:', initialDate)

const formatDisplayDate = (date: string): string => {
  return dateService.formatDisplayDate(date, {
    weekday: true,
    year: true,
    month: 'long',
  })
}

const loadData = async (): Promise<void> => {
  if (!selectedDate.value) return

  try {
    loading.value = true
    error.value = null

    debugLog('Loading daily timesheet data for:', selectedDate.value)

    summary.value = await getDailyTimesheetSummary(selectedDate.value)

    debugLog('Loaded summary:', summary.value)
  } catch (err) {
    debugLog('Error loading timesheet data:', err)
    error.value = 'Failed to load timesheet data. Please try again.'
  } finally {
    loading.value = false
  }
}

const refreshData = (): void => {
  loadData()
}

const navigateDate = (days: number): void => {
  selectedDate.value = navigateDay(selectedDate.value, days)
  updateRoute()
  loadData()
}

const goToToday = (): void => {
  selectedDate.value = today()
  updateRoute()
  loadData()
}

const updateRoute = () => {
  router.push({
    query: {
      date: selectedDate.value,
    },
  })
}

const openStaffModal = (staff: StaffDailyData): void => {
  selectedStaff.value = staff
  showStaffModal.value = true
}

const closeStaffModal = (): void => {
  selectedStaff.value = null
  showStaffModal.value = false
}

const openMetricsModal = (): void => {
  showMetricsModal.value = true
}

const closeMetricsModal = (): void => {
  showMetricsModal.value = false
}

onMounted(() => {
  loadData()
})

watch(
  () => route.query.date,
  (newDate) => {
    if (newDate && newDate !== selectedDate.value) {
      debugLog('Updating date from URL:', newDate)
      selectedDate.value = newDate as string
      loadData()
    }
  },
  { immediate: false },
)

watch(selectedDate, (newDate) => {
  if (newDate && newDate !== route.query.date) {
    debugLog('Updating URL from date change:', newDate)
    updateRoute()
  }
})
</script>
