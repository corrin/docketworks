<template>
  <AppLayout>
    <div class="bg-gray-50 min-h-screen flex flex-col">
      <div
        v-if="loading"
        class="sticky top-0 z-20 py-5 bg-white border-b border-gray-200 flex items-center justify-center min-h-[120px]"
      >
        <div class="flex flex-col items-center w-full">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600 mb-2"></div>
          <span class="text-gray-600 text-sm">Loading timesheet data...</span>
        </div>
      </div>
      <div v-else class="flex-1 flex flex-col">
        <div class="block lg:hidden pt-4">
          <div class="flex items-center justify-between p-3 border-b border-gray-200 bg-white">
            <div class="flex items-center space-x-2">
              <Avatar class="h-8 w-8 ring-2 ring-gray-300">
                <AvatarFallback class="bg-gray-600 text-white font-bold text-xs">
                  {{ getStaffInitials(currentStaff) }}
                </AvatarFallback>
              </Avatar>

              <div class="flex items-center space-x-1">
                <Button
                  variant="ghost"
                  size="sm"
                  @click="navigateStaff(-1)"
                  :disabled="!canNavigateStaff(-1)"
                  class="h-7 w-7 p-0 text-gray-600 hover:bg-gray-100"
                >
                  <ChevronLeft class="h-3 w-3" />
                </Button>

                <Select
                  v-model="selectedStaffId"
                  @update:model-value="(value) => handleStaffChange(value as string)"
                >
                  <SelectTrigger class="h-7 w-32 text-xs bg-white border-gray-300 text-gray-900">
                    <SelectValue placeholder="Staff..." />
                  </SelectTrigger>
                  <SelectContent class="bg-white border-gray-200">
                    <SelectItem
                      v-for="staff in timesheetStore.staff"
                      :key="staff.id"
                      :value="staff.id"
                      class="text-gray-900 hover:bg-gray-100 text-xs"
                    >
                      {{ staff.firstName }} {{ staff.lastName }}
                    </SelectItem>
                  </SelectContent>
                </Select>

                <Button
                  variant="ghost"
                  size="sm"
                  @click="navigateStaff(1)"
                  :disabled="!canNavigateStaff(1)"
                  class="h-7 w-7 p-0 text-gray-600 hover:bg-gray-100"
                >
                  <ChevronRight class="h-3 w-3" />
                </Button>
              </div>
            </div>

            <div class="text-xs">
              <span class="font-semibold" :class="hoursStatusClass">{{
                formatHoursDisplay(todayStats.totalHours)
              }}</span>
              <span class="text-gray-400"> / {{ formatHoursDisplay(scheduledHours) }}</span>
            </div>
          </div>

          <div class="flex items-center justify-between p-3 bg-white">
            <div class="flex items-center space-x-1">
              <Button
                variant="ghost"
                size="sm"
                @click="navigateDate(-1)"
                class="h-7 w-7 p-0 text-gray-600 hover:bg-gray-100"
              >
                <ChevronLeft class="h-3 w-3" />
              </Button>

              <div
                class="text-gray-900 font-medium text-xs px-2 py-1 bg-gray-100 rounded border border-gray-300"
              >
                {{ formatShortDate(currentDate) }}
              </div>

              <Button
                variant="ghost"
                size="sm"
                @click="navigateDate(1)"
                class="h-7 w-7 p-0 text-gray-600 hover:bg-gray-100"
              >
                <ChevronRight class="h-3 w-3" />
              </Button>

              <Button
                variant="ghost"
                size="sm"
                @click="goToToday"
                class="h-7 text-xs px-2 text-gray-600 hover:bg-gray-100"
              >
                Today
              </Button>

              <Button
                variant="ghost"
                size="sm"
                @click="goToDailyOverview"
                class="h-7 text-xs px-2 text-gray-600 hover:bg-gray-100"
              >
                Daily Overview
              </Button>
            </div>

            <div class="flex items-center space-x-1">
              <Button
                @click="addNewEntry"
                size="sm"
                variant="default"
                class="h-7 text-xs px-2 bg-gray-600 hover:bg-gray-700 text-white border-gray-500"
              >
                <Plus class="h-3 w-3" />
              </Button>

              <Button
                @click="refreshData"
                variant="ghost"
                size="sm"
                :disabled="loading"
                class="h-7 w-7 p-0 text-gray-600 hover:bg-gray-100"
              >
                <RefreshCw :class="['h-3 w-3', { 'animate-spin': loading }]" />
              </Button>

              <Button
                @click="showHelpModal = true"
                variant="ghost"
                size="sm"
                class="h-7 w-7 p-0 text-gray-600 hover:bg-gray-100"
              >
                <HelpCircle class="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>

        <div class="hidden lg:flex items-center h-16 px-6 pt-4 bg-white border-b border-gray-200">
          <div class="flex items-center space-x-4">
            <Avatar class="h-10 w-10 ring-2 ring-gray-300">
              <AvatarFallback class="bg-gray-600 text-white font-bold">
                {{ getStaffInitials(currentStaff) }}
              </AvatarFallback>
            </Avatar>

            <div class="flex items-center space-x-2">
              <Button
                variant="ghost"
                size="sm"
                @click="navigateStaff(-1)"
                :disabled="!canNavigateStaff(-1)"
                class="text-gray-600 hover:bg-gray-100"
              >
                <ChevronLeft class="h-4 w-4" />
              </Button>

              <Select
                v-model="selectedStaffId"
                @update:model-value="(value) => handleStaffChange(value as string)"
              >
                <SelectTrigger class="w-48 bg-white border-gray-300 text-gray-900">
                  <SelectValue placeholder="Select staff..." />
                </SelectTrigger>
                <SelectContent class="bg-white border-gray-200">
                  <SelectItem
                    v-for="staff in timesheetStore.staff"
                    :key="staff.id"
                    :value="staff.id"
                    class="text-gray-900 hover:bg-gray-100"
                  >
                    {{ staff.firstName }} {{ staff.lastName }}
                  </SelectItem>
                </SelectContent>
              </Select>

              <Button
                variant="ghost"
                size="sm"
                @click="navigateStaff(1)"
                :disabled="!canNavigateStaff(1)"
                class="text-gray-600 hover:bg-gray-100"
              >
                <ChevronRight class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div class="flex items-center space-x-2 mx-6">
            <Button
              variant="ghost"
              size="sm"
              @click="navigateDate(-1)"
              class="text-gray-600 hover:bg-gray-100"
            >
              <ChevronLeft class="h-4 w-4" />
            </Button>

            <div
              class="text-gray-900 font-semibold px-4 py-2 bg-gray-100 rounded-md border border-gray-300"
            >
              {{ formatDisplayDate(currentDate) }}
            </div>

            <Button
              variant="ghost"
              size="sm"
              @click="navigateDate(1)"
              class="text-gray-600 hover:bg-gray-100"
            >
              <ChevronRight class="h-4 w-4" />
            </Button>

            <Button
              variant="ghost"
              size="sm"
              @click="goToToday"
              class="text-gray-600 hover:bg-gray-100 ml-2"
            >
              Today
            </Button>

            <Button
              variant="ghost"
              size="sm"
              @click="goToDailyOverview"
              class="text-gray-600 hover:bg-gray-100 ml-2"
            >
              Daily Overview
            </Button>
          </div>

          <div class="flex items-center space-x-2 ml-auto">
            <div class="text-xs mr-4">
              <span class="font-semibold" :class="hoursStatusClass">{{
                formatHoursDisplay(todayStats.totalHours)
              }}</span>
              <span class="text-gray-400"> / {{ formatHoursDisplay(scheduledHours) }}</span>
            </div>

            <Button
              data-automation-id="TimesheetEntryView-add-entry"
              @click="addNewEntry"
              size="sm"
              variant="default"
              class="bg-gray-600 hover:bg-gray-700 text-white border-gray-500"
            >
              <Plus class="h-4 w-4 mr-1" />
              Add Entry
            </Button>

            <Button
              @click="refreshData"
              variant="ghost"
              size="sm"
              :disabled="loading"
              class="text-gray-600 hover:bg-gray-100"
            >
              <RefreshCw :class="['h-4 w-4', { 'animate-spin': loading }]" />
            </Button>

            <Button
              @click="showHelpModal = true"
              variant="ghost"
              size="sm"
              class="text-gray-600 hover:bg-gray-100"
            >
              <HelpCircle class="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div
          class="flex-1 flex flex-col overflow-hidden"
          :class="'h-[calc(100vh-6rem)] lg:h-[calc(100vh-4rem)]'"
        >
          <div v-if="loading" class="flex-1 flex items-center justify-center bg-gray-50">
            <div class="text-center">
              <div
                class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-600 mx-auto mb-4"
              ></div>
              <p class="text-gray-600 text-sm lg:text-base">Loading timesheet...</p>
            </div>
          </div>

          <div v-else-if="error" class="flex-1 flex items-center justify-center">
            <div class="text-center px-4">
              <AlertTriangle class="h-8 w-8 lg:h-12 lg:w-12 text-red-500 mx-auto mb-4" />
              <h3 class="text-base lg:text-lg font-semibold text-gray-900 mb-2">
                Error Loading Timesheet
              </h3>
              <p class="text-sm lg:text-base text-gray-600 mb-4">{{ error }}</p>
              <Button @click="reloadData" variant="outline" size="sm">
                <RefreshCw class="h-3 w-3 lg:h-4 lg:w-4 mr-2" />
                Retry
              </Button>
            </div>
          </div>

          <div
            v-else
            class="flex-1 bg-white shadow-sm border border-gray-200 rounded-lg m-2 lg:m-4 overflow-hidden"
          >
            <div class="h-full">
              <AgGridVue
                ref="agGridRef"
                class="h-full ag-theme-custom ag-theme-responsive"
                :columnDefs="columnDefs"
                :rowData="gridData"
                :gridOptions="gridOptions"
                @grid-ready="onGridReady"
                @first-data-rendered="onFirstDataRendered"
              />
            </div>
          </div>
        </div>

        <Dialog v-model:open="showHelpModal">
          <DialogContent class="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Keyboard Shortcuts</DialogTitle>
            </DialogHeader>
            <div class="space-y-3">
              <div class="flex justify-between">
                <span class="text-sm text-slate-600">Add new entry</span>
                <kbd class="px-2 py-1 bg-slate-100 rounded text-xs">Ctrl+N</kbd>
              </div>
              <div class="flex justify-between">
                <span class="text-sm text-slate-600">Check save status</span>
                <kbd class="px-2 py-1 bg-slate-100 rounded text-xs">Ctrl+S</kbd>
              </div>
              <div class="flex justify-between">
                <span class="text-sm text-slate-600">Delete entry</span>
                <kbd class="px-2 py-1 bg-slate-100 rounded text-xs">Delete</kbd>
              </div>
              <div class="flex justify-between">
                <span class="text-sm text-slate-600">Navigate entries</span>
                <kbd class="px-2 py-1 bg-slate-100 rounded text-xs">Tab / Enter</kbd>
              </div>
            </div>
          </DialogContent>
        </Dialog>

        <!-- Bottom Summary Section -->
        <div class="bg-white border-t border-gray-200 mt-4 h-80">
          <div class="flex flex-col lg:flex-row h-full">
            <!-- Current Jobs Section - Left Side (70%) -->
            <div
              class="flex-1 lg:w-[70%] border-b lg:border-b-0 lg:border-r border-gray-100 overflow-hidden"
            >
              <div class="h-full flex flex-col">
                <div class="p-3 border-b border-gray-100 bg-gray-50">
                  <h3 class="text-base font-semibold">Current Jobs</h3>
                </div>

                <div class="flex-1 overflow-y-auto p-3">
                  <div v-if="activeJobsWithData.length === 0" class="text-center py-8">
                    <p class="text-gray-500 text-sm">No active jobs with timesheet entries found</p>
                  </div>

                  <div
                    v-else
                    class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3"
                  >
                    <div
                      v-for="jobData in activeJobsWithData"
                      :key="jobData.job.id"
                      class="bg-white border border-gray-200 rounded-lg p-3 hover:shadow-md transition-shadow cursor-pointer"
                      @click="navigateToJob(jobData.job.id)"
                    >
                      <!-- Job Header -->
                      <div class="flex items-start justify-between mb-2">
                        <div class="flex-1 min-w-0">
                          <h4
                            class="font-medium text-blue-600 hover:text-blue-800 transition-colors text-sm truncate"
                          >
                            {{ jobData.job.job_number }}
                          </h4>
                          <p class="text-xs text-gray-600 truncate">{{ jobData.job.name }}</p>
                          <p class="text-xs text-gray-500 truncate">
                            {{ jobData.job.client_name }}
                          </p>
                        </div>
                        <Badge
                          :variant="getStatusVariant(resolveJobStatus(jobData.job))"
                          class="text-xs"
                        >
                          {{ getStatusLabel(resolveJobStatus(jobData.job)) }}
                        </Badge>
                      </div>

                      <!-- Hours Progress -->
                      <div class="space-y-2 mb-3">
                        <div class="flex justify-between text-xs">
                          <span class="text-gray-600">Progress</span>
                          <span class="font-medium">
                            {{ formatHoursDisplay(jobData.actualHours) }}
                            <span v-if="jobData.estimatedHours > 0">
                              / {{ formatHoursDisplay(jobData.estimatedHours) }}
                            </span>
                          </span>
                        </div>

                        <!-- Always show progress bar -->
                        <div class="w-full bg-gray-200 rounded-full h-2">
                          <div
                            class="h-2 rounded-full transition-all duration-300"
                            :class="
                              jobData.isOverBudget
                                ? 'bg-red-500'
                                : jobData.estimatedHours > 0
                                  ? 'bg-blue-500'
                                  : 'bg-gray-400'
                            "
                            :style="{
                              width:
                                jobData.estimatedHours > 0
                                  ? `${Math.min(jobData.completionPercentage, 100)}%`
                                  : `${Math.min((jobData.actualHours / 8) * 100, 100)}%`,
                            }"
                          ></div>
                        </div>

                        <div class="flex justify-between text-xs">
                          <span :class="jobData.isOverBudget ? 'text-red-600' : 'text-gray-600'">
                            <span v-if="jobData.estimatedHours > 0">
                              {{ jobData.completionPercentage.toFixed(1) }}% complete
                            </span>
                            <span v-else>
                              {{ formatHoursDisplay(jobData.actualHours) }} logged
                            </span>
                          </span>
                          <span v-if="jobData.isOverBudget" class="text-red-600 font-medium">
                            Over Budget
                          </span>
                          <span
                            v-else-if="jobData.estimatedHours <= 0"
                            class="text-gray-500 text-xs"
                          >
                            No estimate
                          </span>
                        </div>
                      </div>

                      <!-- Financial Info -->
                      <div class="flex justify-between items-center pt-2 border-t border-gray-100">
                        <div class="text-xs">
                          <span class="text-gray-600">Bill:</span>
                          <span class="font-semibold ml-1">{{
                            formatCurrency(jobData.totalBill)
                          }}</span>
                        </div>
                        <ExternalLink class="h-3 w-3 text-gray-400" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Daily Breakdown Section - Right Side (30%) -->
            <div class="w-full lg:w-[30%] overflow-hidden">
              <div class="h-full flex flex-col">
                <div class="p-3 border-b border-gray-100 bg-gray-50">
                  <h3 class="text-base font-semibold">Daily Breakdown</h3>
                </div>

                <div class="flex-1 overflow-y-auto p-3">
                  <div class="grid grid-cols-2 gap-4">
                    <!-- Hours & Bill Column -->
                    <div class="space-y-3">
                      <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex items-center space-x-3">
                          <Clock class="h-5 w-5 text-blue-600 flex-shrink-0" />
                          <div class="min-w-0">
                            <p class="text-sm text-gray-600">Total Hours</p>
                            <p class="text-lg font-semibold">
                              <span :class="hoursStatusClass">{{
                                formatHoursDisplay(consolidatedSummary.totalHours)
                              }}</span>
                              <span class="text-sm font-normal text-gray-400"
                                >/ {{ formatHoursDisplay(scheduledHours) }}</span
                              >
                            </p>
                          </div>
                        </div>
                      </div>

                      <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex items-center space-x-3">
                          <DollarSign class="h-5 w-5 text-green-600 flex-shrink-0" />
                          <div class="min-w-0">
                            <p class="text-sm text-gray-600">Total Bill</p>
                            <p class="text-lg font-semibold">
                              {{ formatCurrency(consolidatedSummary.totalBill) }}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- Billable & Non-Billable Column -->
                    <div class="space-y-3">
                      <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex items-center space-x-3">
                          <CheckCircle class="h-5 w-5 text-green-600 flex-shrink-0" />
                          <div class="min-w-0">
                            <p class="text-sm text-gray-600">Billable</p>
                            <p class="text-lg font-semibold">
                              {{ consolidatedSummary.billableEntries }}
                            </p>
                          </div>
                        </div>
                      </div>

                      <div class="bg-gray-50 rounded-lg p-4">
                        <div class="flex items-center space-x-3">
                          <XCircle class="h-5 w-5 text-gray-600 flex-shrink-0" />
                          <div class="min-w-0">
                            <p class="text-sm text-gray-600">Non-Billable</p>
                            <p class="text-lg font-semibold">
                              {{ consolidatedSummary.nonBillableEntries }}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { AgGridVue } from 'ag-grid-vue3'
import type { GridReadyEvent, RowNode } from 'ag-grid-community'
import { v4 as uuidv4 } from 'uuid'
import { debounce } from 'lodash-es'

import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'

import {
  ChevronLeft,
  ChevronRight,
  Plus,
  HelpCircle,
  AlertTriangle,
  RefreshCw,
  Clock,
  DollarSign,
  CheckCircle,
  XCircle,
  ExternalLink,
} from 'lucide-vue-next'
import { useTimesheetAutosave } from '@/composables/useTimesheetAutosave'
import { useTimesheetSummary } from '@/composables/useTimesheetSummary'
import { toast } from 'vue-sonner'
import { formatCurrency, formatHoursDisplay } from '@/utils/string-formatting'

import { useTimesheetEntryGrid } from '@/composables/useTimesheetEntryGrid'
import { useTimesheetStore } from '@/stores/timesheet'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import * as costlineService from '@/services/costline.service'
import { jobService } from '@/services/job.service'
import { api } from '@/api/client'

// Import types from generated API schemas
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

import { debugLog } from '@/utils/debug'
import { toLocalDateString } from '@/utils/dateUtils'
import type { TimesheetEntryWithMeta } from '@/constants/timesheet'
type RateMultiplierMetaRecord = Record<string, unknown> & {
  wage_rate_multiplier?: number
}

type ModernTimesheetJob = z.infer<typeof schemas.ModernTimesheetJob>
type Staff = z.infer<typeof schemas.ModernStaff>
type TimesheetCostLine = z.infer<typeof schemas.TimesheetCostLine>
type Job = z.infer<typeof schemas.Job>
type JobSummary = z.infer<typeof schemas.JobSummary>

type TimesheetEntryViewRow = TimesheetEntryWithMeta

type ActiveJobWithData = {
  job: Job | JobSummary | ModernTimesheetJob
  actualHours: number
  estimatedHours: number
  totalBill: number
  completionPercentage: number
  isOverBudget: boolean
}

const resolveJobStatus = (job: Job | JobSummary | ModernTimesheetJob): string => {
  if ('job_status' in job && typeof job.job_status === 'string' && job.job_status) {
    return job.job_status
  }
  if ('status' in job && typeof job.status === 'string' && job.status) {
    return job.status
  }
  return 'draft'
}

// Type for autosave callback
type TimesheetEntryGridRowWithSaving = TimesheetEntryWithMeta

const router = useRouter()
const route = useRoute()
const timesheetStore = useTimesheetStore()
const companyDefaultsStore = useCompanyDefaultsStore()

const loading = ref(false)
const error = ref<string | null>(null)
const showHelpModal = ref(false)
const agGridRef = ref()

const todayDate = toLocalDateString()
debugLog('Today is:', todayDate, 'Day of week:', new Date().getDay())

const initialDate = (route.query.date as string) || todayDate
const initialStaffId = (route.query.staffId as string) || ''

const descriptionEditingRows = new Set<string>()

function getRowKey(entry: { id?: unknown; tempId?: unknown } | null | undefined): string | null {
  if (!entry) return null
  if (entry.id != null && String(entry.id) !== '') return String(entry.id)
  if (entry.tempId != null && String(entry.tempId) !== '') return String(entry.tempId)
  return null
}

function setDescriptionEditingState(
  entry: { id?: unknown; tempId?: unknown } | null | undefined,
  isEditing: boolean,
): void {
  const key = getRowKey(entry)
  if (!key) return
  if (isEditing) {
    descriptionEditingRows.add(key)
  } else {
    descriptionEditingRows.delete(key)
  }
}

function isDescriptionBeingEdited(
  entry: { id?: unknown; tempId?: unknown } | null | undefined,
): boolean {
  const key = getRowKey(entry)
  return key ? descriptionEditingRows.has(key) : false
}

function toMetaRecord(meta: unknown): Record<string, unknown> | null {
  if (meta && typeof meta === 'object') {
    return meta as Record<string, unknown>
  }
  return null
}

debugLog('URL params:', { date: route.query.date, staffId: route.query.staffId })
debugLog('Using initial values:', { date: initialDate, staffId: initialStaffId })

const currentDate = ref<string>(initialDate)
const selectedStaffId = ref<string>(initialStaffId)
const isInitializing = ref(true)
const isLoadingData = ref(false) // ✅ Add loading flag to prevent duplicate calls

const timeEntries = ref<TimesheetEntryViewRow[]>([])
const scheduledHours = ref<number>(0)

// Adapter to convert TimesheetEntryView data format to TimesheetCostLine format
const adaptedTimeEntries = computed(() => {
  const adapted = timeEntries.value.map((entry) => ({
    ...entry,
  }))

  debugLog('adaptedTimeEntries:', {
    originalCount: timeEntries.value.length,
    adaptedCount: adapted.length,
    originalSample: timeEntries.value.slice(0, 2).map((e) => ({
      id: e.id,
      job_id: e.job_id,
      job_number: e.job_number,
    })),
    adaptedSample: adapted.slice(0, 2).map((e) => ({
      id: e.id,
      job_id: e.job_id,
      job_number: e.job_number,
    })),
    uniqueJobIds: [...new Set(adapted.map((e) => e.job_id))],
  })

  return adapted
})

// Computed property to ensure jobs are always available
const availableJobs = computed(() => {
  debugLog('availableJobs computed - jobs count:', timesheetStore.jobs.length)
  return timesheetStore.jobs || []
})

const currentStaff = computed(() => {
  const staff = timesheetStore.staff.find((s: Staff) => s.id === selectedStaffId.value) || null
  setCurrentStaff(staff)
  return staff
})

const hasUnsavedChanges = ref(false)

const hoursStatusClass = computed(() => {
  const actual = timeEntries.value.reduce((sum, entry) => sum + getEntryHours(entry), 0)
  const scheduled = scheduledHours.value
  if (actual > scheduled) return 'text-red-600'
  if (actual < scheduled) return 'text-amber-500'
  return 'text-gray-900'
})

const todayStats = computed(() => {
  const totalHours = timeEntries.value.reduce((sum, entry) => sum + getEntryHours(entry), 0)
  const totalBill = timeEntries.value.reduce(
    (sum, entry) => sum + (entry.bill ?? entry.total_rev ?? 0),
    0,
  )
  const entryCount = timeEntries.value.length

  return {
    totalHours,
    totalBill,
    entryCount,
  }
})

const companyDefaultsRef = computed(() => companyDefaultsStore.companyDefaults)

// Summary logic
const {
  getActiveJobs,
  getJobBill,
  getCompletionPercentage,
  isJobOverBudget,
  getTotalHours,
  getTotalBill,
  getBillableEntries,
  getNonBillableEntries,
  navigateToJob,
  getStatusVariant,
  getStatusLabel,
  getEstimatedHours,
} = useTimesheetSummary()

const getEntryHours = (entry: TimesheetEntryViewRow): number => {
  return entry.hours ?? entry.quantity ?? 0
}

async function handleApproveCostLine(id: string): Promise<void> {
  const toastId = toast.loading('Approving entry...')
  try {
    await api.approveCostLine(undefined, { params: { cost_line_id: id } })
    toast.success('Entry approved', { id: toastId })
    await loadTimesheetData()
  } catch (error) {
    console.error('Failed to approve cost line:', error)
    toast.error('Failed to approve entry', { id: toastId })
  }
}

const getJobHours = (jobId: string, timeEntries: TimesheetEntryViewRow[]) => {
  const jobEntries = timeEntries.filter((entry) => entry.job_id === jobId)

  const hours = jobEntries.reduce((sum, entry) => sum + getEntryHours(entry), 0)

  debugLog(`getJobHours (local) for jobId ${jobId}:`, {
    jobId,
    totalEntries: timeEntries.length,
    matchingEntries: jobEntries.length,
    allJobIds: timeEntries.map((e) => e.job_id),
    matchingJobIds: jobEntries.map((e) => e.job_id),
    hours,
    entriesDetails: jobEntries.map((e) => ({
      id: e.id,
      job_id: e.job_id,
      quantity: e.quantity,
    })),
  })

  return hours
}

// Enhanced jobs state for job details with full data
const enhancedJobs = ref<Map<string, Job | JobSummary>>(new Map())

// Function to load enhanced job data ONLY for jobs with timesheet entries
const loadEnhancedJobData = async (jobIds: string[]) => {
  try {
    // Filter to only jobs we haven't loaded yet
    const jobsToLoad = jobIds.filter((id) => !enhancedJobs.value.has(id))

    if (jobsToLoad.length === 0) {
      debugLog('All enhanced job data already loaded')
      return
    }

    debugLog(
      'Loading enhanced job data for jobs with timesheet entries:',
      jobsToLoad.length,
      'jobs',
    )

    // Load all jobs in parallel instead of sequentially
    const results = await Promise.allSettled(
      jobsToLoad.map(async (jobId) => {
        const summaryResponse = await jobService.getJobSummary(jobId)
        return { jobId, job: summaryResponse.data.job }
      }),
    )

    // Process results
    for (const result of results) {
      if (result.status === 'fulfilled') {
        const { jobId, job } = result.value
        enhancedJobs.value.set(jobId, job)
        debugLog('Loaded enhanced job data:', {
          jobId,
          jobNumber: job.job_number,
          latest_estimate: job.latest_estimate?.summary,
          latest_quote: job.latest_quote?.summary,
        })
      } else {
        debugLog('Failed to load enhanced job data:', result.reason)
      }
    }
  } catch (err) {
    debugLog('Error loading enhanced job data:', err)
  }
}

// Computed properties for summary
const activeJobs = computed(() => {
  return getActiveJobs(availableJobs.value)
})

const consolidatedSummary = computed(() => {
  const costLineEntries = adaptedTimeEntries.value as TimesheetEntryViewRow[]
  return {
    totalHours: getTotalHours(costLineEntries),
    totalBill: getTotalBill(costLineEntries),
    billableEntries: getBillableEntries(costLineEntries),
    nonBillableEntries: getNonBillableEntries(costLineEntries),
    activeJobs: activeJobs.value.length,
  }
})

const activeJobsWithData = computed<ActiveJobWithData[]>(() => {
  const costLineEntries = adaptedTimeEntries.value as TimesheetEntryViewRow[]
  const uniqueJobIds = [
    ...new Set(
      costLineEntries.map((entry) => entry.job_id).filter((id): id is string => Boolean(id)),
    ),
  ]

  debugLog('activeJobsWithData:', {
    adaptedEntriesCount: adaptedTimeEntries.value.length,
    uniqueJobIdsFromEntries: uniqueJobIds,
    activeJobsCount: activeJobs.value.length,
    activeJobIds: activeJobs.value.map((job) => job.id),
    mismatch: uniqueJobIds.some((id) => !activeJobs.value.find((job) => job.id === id)),
  })

  const jobsWithData: ActiveJobWithData[] = uniqueJobIds
    .map((jobId) => {
      const actualHours = getJobHours(jobId, costLineEntries)

      // Skip jobs without timesheet entries (shouldn't happen since we're filtering by entries)
      if (actualHours === 0) {
        debugLog(`Job ${jobId} has 0 hours despite being in entries`)
        return null
      }

      // Try to find job in activeJobs first, then in all jobs
      let job =
        activeJobs.value.find((j) => j.id === jobId) ||
        timesheetStore.jobs.find((j) => j.id === jobId)

      if (!job) {
        // Create a minimal job object from timesheet entry data
        const entryWithJobData = costLineEntries.find((entry) => entry.job_id === jobId)
        if (entryWithJobData) {
          const metaLeaveType =
            entryWithJobData.meta &&
            typeof entryWithJobData.meta === 'object' &&
            'leave_type' in entryWithJobData.meta
              ? (entryWithJobData.meta as Record<string, unknown>).leave_type
              : undefined
          job = {
            id: jobId,
            job_number: Number(entryWithJobData.job_number) || 0,
            name: entryWithJobData.job_name || 'Unknown Job',
            has_actual_costset: true,
            client_name: entryWithJobData.client_name || 'Unknown Client',
            status: 'draft',
            charge_out_rate: entryWithJobData.charge_out_rate || 0,
            leave_type: typeof metaLeaveType === 'string' ? metaLeaveType : 'time',
          } as ModernTimesheetJob

          debugLog(`Created minimal job object for ${jobId}:`, job)
        } else {
          debugLog(`Could not find or create job data for ${jobId}`)
          return null
        }
      }

      // Use enhanced job data if available, otherwise use basic job data
      const enhancedJob = enhancedJobs.value.get(jobId)

      const estimatedHours = enhancedJob ? getEstimatedHours(enhancedJob) : 0
      const totalBill = getJobBill(jobId, costLineEntries)
      const completionPercentage = getCompletionPercentage(actualHours, estimatedHours)
      const isOverBudget = isJobOverBudget(actualHours, estimatedHours)

      debugLog(`Job ${job.job_number} (${jobId}):`, {
        actualHours,
        estimatedHours,
        totalBill,
        completionPercentage,
        isOverBudget,
      })

      return {
        job: enhancedJob || job, // Use enhanced job if available
        actualHours,
        estimatedHours,
        totalBill,
        completionPercentage,
        isOverBudget,
      }
    })
    .filter((jobData): jobData is ActiveJobWithData => jobData !== null) // Remove null entries
    .sort((a, b) => b.actualHours - a.actualHours) // Sort by hours worked (descending)

  debugLog('Active jobs with data (FIXED):', jobsWithData.length, jobsWithData)
  return jobsWithData
})

// Watch for changes in jobs WITH timesheet entries and load enhanced data
watch(
  () => activeJobsWithData.value.map((jobData) => jobData.job.id),
  async (newJobIds) => {
    if (newJobIds.length > 0) {
      debugLog(
        'Jobs with timesheet entries changed, loading enhanced data for:',
        newJobIds.length,
        'jobs',
      )
      await loadEnhancedJobData(newJobIds)
    }
  },
  { immediate: false }, // Don't run immediately to avoid circular dependency
)
const jobsForGrid = computed<Record<string, unknown>[]>(() =>
  timesheetStore.jobs.map((job) => job as Record<string, unknown>),
)

const {
  gridData,
  columnDefs,
  gridOptions,
  setGridApi,
  loadData,
  addNewRow,
  handleKeyboardShortcut,
  setCurrentStaff,
  createEntryFromRow,
  getIncompleteDraftRows,
} = useTimesheetEntryGrid(
  companyDefaultsRef,
  jobsForGrid, // Pass jobs from timesheet store
  handleSaveEntry,
  handleDeleteEntry,
  {
    resolveStaffById: (id: string) => timesheetStore.staff.find((s) => s.id === id),
    onDescriptionEditChange: (entry: TimesheetEntryGridRowWithSaving, isEditing: boolean) => {
      setDescriptionEditingState(entry, isEditing)
    },
    onScheduleAutosave: (entry: TimesheetEntryGridRowWithSaving) => {
      const rows = gridData.value as TimesheetEntryViewRow[]

      if (entry.id != null && String(entry.id) !== '') {
        autosave.schedule(String(entry.id))
        return
      }

      // if it has tempId, try to promote
      if (!entry.tempId) return

      const now = rows.find((r) => r.tempId && String(r.tempId) === String(entry.tempId))
      if (now?.id != null && String(now.id) !== '') {
        entry.id = now.id
        delete entry.tempId
        autosave.schedule(String(now.id))
      } else {
        autosave.schedule(String(entry.tempId))
      }
    },
    approveRow: (id: string) => {
      void handleApproveCostLine(id)
    },
  },
)

const autosave = useTimesheetAutosave<TimesheetEntryViewRow>({
  getRowKey: (entry) => {
    if (entry.id != null && String(entry.id) !== '') return String(entry.id)

    if (entry.tempId) {
      const rows = gridData.value as TimesheetEntryViewRow[]
      const found = rows.find((r) => r.tempId === entry.tempId)
      if (found?.id != null && String(found.id) !== '') return String(found.id)
      return entry.tempId
    }

    return undefined
  },
  getEntry: (rowKey) => {
    const rows = gridData.value as unknown as TimesheetEntryViewRow[]

    const byId = rows.find(
      (r) => r.id !== null && r.id !== undefined && String(r.id) === String(rowKey),
    )

    if (byId) {
      const normalized = createEntryFromRow(byId)
      console.log('[DEBUG] getEntry found by id:', {
        rowKey,
        hours: normalized.hours,
        quantity: normalized.quantity,
        jobNumber: normalized.jobNumber,
        job_number: normalized.job_number,
        description: normalized.description,
        rate: normalized.rate,
        billable: normalized.billable,
      })
      return normalized
    }

    const byTemp = rows.find((r) => r.tempId && String(r.tempId) === String(rowKey))
    if (byTemp) {
      const normalized = createEntryFromRow(byTemp)
      console.log('[DEBUG] getEntry found by tempId:', {
        rowKey,
        hours: normalized.hours,
        quantity: normalized.quantity,
        jobNumber: normalized.jobNumber,
        job_number: normalized.job_number,
        description: normalized.description,
        rate: normalized.rate,
        billable: normalized.billable,
      })
      return normalized
    }

    return null
  },
  isRowComplete: (e) => {
    // Check both UI field names (jobNumber, hours) and backend field names (job_id, job_number, quantity)
    const hasJob = Boolean(e.job_id || e.job_number || e.jobNumber)
    const hasHours = Number(e.quantity || e.hours || 0) > 0
    const isEditingDescription = isDescriptionBeingEdited(e)
    const isComplete = hasJob && hasHours && !isEditingDescription
    if (!isComplete) {
      console.log('[DEBUG] isRowComplete FAILED:', {
        hasJob,
        hasHours,
        isEditingDescription,
        job_id: e.job_id,
        job_number: e.job_number,
        jobNumber: e.jobNumber,
        quantity: e.quantity,
        hours: e.hours,
        tempId: e.tempId,
        id: e.id,
      })
    }
    return isComplete
  },
  isDuplicate: (e) => {
    if (e.id) return false
    const rows = gridData.value as TimesheetEntryViewRow[]
    return rows.some(
      (row) =>
        !!row.id &&
        row.job_number === e.job_number &&
        row.date === e.date &&
        row.meta &&
        typeof row.meta === 'object' &&
        typeof e.meta === 'object' &&
        (row.meta as Record<string, unknown>).staff_id ===
          (e.meta as Record<string, unknown>).staff_id &&
        String(row.desc || '').trim() === String(e.desc || '').trim(),
    )
  },
  save: async (e) => {
    await handleSaveEntry(e)
  },
  softRefresh: async (e) => {
    await softRefreshRow(e)
  },
})

const warnIncompleteDrafts = (): void => {
  const drafts = getIncompleteDraftRows()
  for (const row of drafts) {
    const jobValue = row.jobNumber || row.job_number
    const jobPart = jobValue ? `job ${jobValue}` : '(no job)'
    const missing = !jobValue ? 'a job number' : 'hours'
    toast.warning(`Entry for ${jobPart} not saved — needs ${missing}`, { duration: 6000 })
  }
}

const canNavigateStaff = (direction: number): boolean => {
  if (!timesheetStore.staff.length) return false
  const currentIndex = timesheetStore.staff.findIndex((s) => s.id === selectedStaffId.value)
  if (currentIndex === -1) return false

  const newIndex = currentIndex + direction
  return newIndex >= 0 && newIndex < timesheetStore.staff.length
}

const navigateStaff = (direction: number) => {
  if (!canNavigateStaff(direction)) return

  const currentIndex = timesheetStore.staff.findIndex((s) => s.id === selectedStaffId.value)
  const newIndex = currentIndex + direction
  const newStaff = timesheetStore.staff[newIndex]

  if (newStaff) {
    warnIncompleteDrafts()
    selectedStaffId.value = newStaff.id
    updateRoute()
  }
}

const navigateDate = (direction: number) => {
  warnIncompleteDrafts()
  const parts = currentDate.value.split('-')
  const year = parseInt(parts[0], 10)
  const month = parseInt(parts[1], 10) - 1
  const day = parseInt(parts[2], 10)

  const date = new Date(year, month, day)

  // Only skip weekends if weekend feature is disabled
  if (!timesheetStore.weekendEnabled) {
    do {
      date.setDate(date.getDate() + direction)
    } while (date.getDay() === 0 || date.getDay() === 6)
  } else {
    date.setDate(date.getDate() + direction)
  }

  const newYear = date.getFullYear()
  const newMonth = String(date.getMonth() + 1).padStart(2, '0')
  const newDay = String(date.getDate()).padStart(2, '0')

  currentDate.value = `${newYear}-${newMonth}-${newDay}`
  debugLog(
    'Navigated to:',
    currentDate.value,
    'Day of week:',
    date.getDay(),
    'Weekend enabled:',
    timesheetStore.weekendEnabled,
  )
  updateRoute()
}

const goToToday = () => {
  warnIncompleteDrafts()
  const today = new Date()

  // Only skip weekends if weekend feature is disabled
  if (!timesheetStore.weekendEnabled) {
    if (today.getDay() === 0) {
      today.setDate(today.getDate() + 1)
    } else if (today.getDay() === 6) {
      today.setDate(today.getDate() + 2)
    }
  }

  const year = today.getFullYear()
  const month = String(today.getMonth() + 1).padStart(2, '0')
  const day = String(today.getDate()).padStart(2, '0')

  currentDate.value = `${year}-${month}-${day}`
  debugLog('Going to today:', currentDate.value, 'Weekend enabled:', timesheetStore.weekendEnabled)
  updateRoute()
}

const goToDailyOverview = () => {
  router.push({
    name: 'timesheet-daily',
    query: {
      date: currentDate.value,
    },
  })
}

const updateRoute = () => {
  router.push({
    query: {
      date: currentDate.value,
      staffId: selectedStaffId.value,
    },
  })
}

const getStaffInitials = (staff: Staff | null): string => {
  if (!staff) return 'U'
  const first = staff.firstName?.[0] || ''
  const last = staff.lastName?.[0] || ''
  return (first + last).toUpperCase() || 'U'
}

const formatDisplayDate = (date: string): string => {
  const parts = date.split('-')
  const year = parseInt(parts[0], 10)
  const month = parseInt(parts[1], 10) - 1
  const day = parseInt(parts[2], 10)

  const d = new Date(year, month, day)

  const formatted = d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })

  return formatted
}

const formatShortDate = (date: string): string => {
  const parts = date.split('-')
  const year = parseInt(parts[0], 10)
  const month = parseInt(parts[1], 10) - 1
  const day = parseInt(parts[2], 10)

  const d = new Date(year, month, day)

  const formatted = d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  })

  return formatted
}

async function handleSaveEntry(entry: TimesheetEntryViewRow): Promise<void> {
  const entryRow = entry
  const hasJob = Boolean(entryRow.job_id || entryRow.job_number)
  const hasDescription = entryRow.desc && entryRow.desc.trim().length > 0
  const hasHours = Number(entryRow.quantity ?? 0) > 0
  const isEditingDescription = isDescriptionBeingEdited(entryRow)

  debugLog('VALIDATION CHECK:', {
    entryId: entryRow.id,
    jobId: entryRow.job_id,
    jobNumber: entryRow.job_number,
    hasJob,
    description: entryRow.description,
    hasDescription,
    hours: entryRow.hours,
    hasHours,
    isEditingDescription,
    validationPassed: hasJob && hasHours && !isEditingDescription,
  })

  if (isEditingDescription) {
    debugLog('VALIDATION SKIP - Description currently being edited, delaying save', {
      entryId: entry.id,
      tempId: entry.tempId,
    })
    return
  }

  if (!hasJob || !hasHours) {
    debugLog('VALIDATION FAILED - Entry not saved:', {
      hasJob,
      hasDescription,
      hasHours,
      entry: {
        id: entryRow.id,
        jobId: entryRow.jobId,
        jobNumber: entryRow.jobNumber,
        description: entryRow.description,
        hours: entryRow.hours,
      },
    })
    return
  }

  if (entryRow._isSaving) return

  try {
    entryRow._isSaving = true

    if (!entryRow.id && !entryRow.tempId) {
      entryRow.tempId = uuidv4()
    }

    const staffId = selectedStaffId.value
    const date = currentDate.value

    let targetJobId = entryRow.jobId
    if (!targetJobId && entryRow.jobNumber) {
      const jobNumber = Number(entryRow.jobNumber)
      const jobByNumber = timesheetStore.jobs.find(
        (j: ModernTimesheetJob) => j.job_number === jobNumber,
      )
      if (jobByNumber) {
        targetJobId = jobByNumber.id
        entryRow.jobId = targetJobId
        entryRow.client = jobByNumber.client_name || ''
        entryRow.jobName = jobByNumber.name || ''
        entryRow.chargeOutRate = jobByNumber.charge_out_rate || 0
      }
    }

    const costLinePayload = {
      kind: 'time' as const,
      desc: entryRow.description,
      quantity: entryRow.hours,
      unit_cost: entryRow.wageRate,
      unit_rev: entryRow.chargeOutRate,
      accounting_date: date,
      xero_pay_item: entryRow.xeroPayItemId,
      meta: {
        staff_id: staffId,
        date: date,
        is_billable: entryRow.billable,
        created_from_timesheet: true,
        wage_rate_multiplier: entryRow.rateMultiplier,
      },
    }

    let savedLine

    if (entryRow.id && String(entryRow.id) !== '') {
      debugLog('UPDATING existing entry:', entryRow.id)
      savedLine = await costlineService.updateCostLine(entryRow.id, costLinePayload)
    } else {
      debugLog('CREATING new entry')
      const job = timesheetStore.jobs.find((j: ModernTimesheetJob) => j.id === targetJobId)
      if (!job) throw new Error('Job not found')
      savedLine = await costlineService.createCostLine(job.id, 'actual', costLinePayload)
    }

    const savedId =
      savedLine && typeof savedLine === 'object' && 'id' in savedLine
        ? String((savedLine as { id?: string | number }).id ?? '')
        : ''
    if (savedId) {
      entryRow.id = savedId
      delete entryRow.tempId
    }

    const entryIndex = timeEntries.value.findIndex((e: TimesheetEntryViewRow) => {
      if (entryRow.id && e.id === entryRow.id) return true
      if (entryRow.tempId && e.tempId === entryRow.tempId) return true
      return false
    })
    if (entryIndex >= 0) {
      timeEntries.value[entryIndex] = {
        ...entryRow,
        ...savedLine,
        isNewRow: false,
        isModified: false,
      }
    } else {
      timeEntries.value.push({ ...entryRow, ...savedLine, isNewRow: false, isModified: false })
    }
  } catch (err) {
    debugLog('Error saving entry:', err)
    error.value = 'Failed to save entry'
  } finally {
    entryRow._isSaving = false
  }
}

/**
 * Soft refresh of a specific row after saving, without blocking the grid.
 * - Searches for current entries in the backend for (staffId, date)
 * - Locates the saved row by ID and applies an authoritative merge to the grid data and timeEntries
 */
async function softRefreshRow(entry: TimesheetEntryViewRow): Promise<void> {
  try {
    const resp = await costlineService.getTimesheetEntries(selectedStaffId.value, currentDate.value)
    const line = resp.cost_lines.find((l: TimesheetCostLine) => String(l.id) === String(entry.id))
    if (!line) return

    const hours = line.quantity
    const staffWageRate = line.wage_rate || line.unit_cost
    const metaRecord = toMetaRecord(line.meta) as RateMultiplierMetaRecord | null
    const rateMultiplier = metaRecord?.wage_rate_multiplier as number

    const calculatedWage =
      hours > 0 && staffWageRate > 0
        ? Math.round(hours * rateMultiplier * staffWageRate * 100) / 100
        : 0

    const normalizedJobId = line.job_id || ''
    const normalizedJobNumber =
      typeof line.job_number === 'number' ? line.job_number : Number(line.job_number) || 0
    const normalizedJobNumberString = line.job_number != null ? String(line.job_number) : ''
    const normalizedClientName = line.client_name || ''
    const normalizedJobName = line.job_name || ''
    const normalizedChargeOutRate = line.charge_out_rate || 0
    const xeroPayItemId = line.xero_pay_item ?? undefined
    const xeroPayItemName = line.xero_pay_item_name ?? undefined

    const merged = {
      id: line.id,
      jobId: normalizedJobId,
      job_id: normalizedJobId,
      jobNumber: normalizedJobNumberString,
      job_number: normalizedJobNumber,
      client: normalizedClientName,
      client_name: normalizedClientName,
      jobName: normalizedJobName,
      job_name: normalizedJobName,
      hours,
      billable:
        typeof metaRecord?.['is_billable'] === 'boolean'
          ? (metaRecord['is_billable'] as boolean)
          : true,
      description: line.desc,
      rate: getRateTypeFromMultiplier(rateMultiplier),
      wage: calculatedWage,
      bill: line.total_rev,
      staffId: selectedStaffId.value,
      date: currentDate.value,
      wageRate: staffWageRate,
      chargeOutRate: normalizedChargeOutRate,
      charge_out_rate: normalizedChargeOutRate,
      rateMultiplier,
      isNewRow: false,
      isModified: false,
      approved: line.approved,
      xeroPayItemId,
      xeroPayItemName,
      xero_pay_item: xeroPayItemId ?? null,
      xero_pay_item_name: xeroPayItemName ?? '',
    } as unknown as TimesheetEntryViewRow

    // Update the grid
    const rows = gridData.value as unknown as TimesheetEntryViewRow[]
    const idx = rows.findIndex(
      (r) =>
        (merged.id && String(r.id) === String(merged.id)) ||
        (r.tempId && entry.tempId && String(r.tempId) === String(entry.tempId)),
    )
    if (idx !== -1) {
      const prev = rows[idx]
      rows[idx] = {
        ...prev,
        ...merged,
        tempId: merged.id ? undefined : prev.tempId,
        _isSaving: false,
        isModified: false,
        isNewRow: false,
      }

      const api = agGridRef.value?.api
      if (api) {
        let targetNode: RowNode | null = null
        api.forEachNode((node: RowNode) => {
          const data = (node as unknown as { data?: TimesheetEntryViewRow }).data
          if (data && String(data.id) === String(merged.id)) targetNode = node
        })
        if (targetNode) {
          ;(targetNode as unknown as { setData: (d: unknown) => void }).setData(
            rows[idx] as unknown,
          )
          nextTick(() => {
            if (api && !api.isDestroyed?.()) {
              api.refreshCells({ rowNodes: [targetNode!] })
            }
          })
        } else {
          nextTick(() => {
            if (api && !api.isDestroyed?.()) {
              api.refreshCells()
            }
          })
        }
      }
    }

    // Update entries to reflect state
    const tRows = timeEntries.value as TimesheetEntryViewRow[]
    const tIdx = tRows.findIndex((r) => r?.id && String(r.id) === String(merged.id))
    if (tIdx !== -1) {
      const prevTE = tRows[tIdx]
      tRows[tIdx] = { ...prevTE, ...merged }
    } else {
      tRows.push(merged)
    }
  } catch (err) {
    debugLog('Soft refresh failed:', err)
  }
}

async function handleDeleteEntry(id: string): Promise<void> {
  try {
    // Keep loading for deletion since it's a critical operation
    loading.value = true

    await costlineService.deleteCostLine(String(id))

    timeEntries.value = timeEntries.value.filter(
      (e: TimesheetEntryViewRow) => String(e.id) !== String(id),
    )

    hasUnsavedChanges.value = false
    debugLog('Entry deleted successfully:', id)
  } catch (err) {
    debugLog('Error deleting entry:', err)
    error.value = 'Failed to delete entry'
  } finally {
    loading.value = false
  }
}

function onGridReady(params: GridReadyEvent) {
  setGridApi(params.api)
}

function onFirstDataRendered() {
  setTimeout(() => agGridRef.value?.api?.sizeColumnsToFit(), 100)
}

const addNewEntry = () => {
  debugLog('Adding new entry for staff:', selectedStaffId.value)

  const staffData = timesheetStore.staff.find((s) => s.id === selectedStaffId.value)

  debugLog('Staff data for new entry:', {
    staffId: selectedStaffId.value,
    staffData: staffData
      ? {
          id: staffData.id,
          name: `${staffData.firstName} ${staffData.lastName}`,
          wageRate: staffData.wageRate,
        }
      : null,
  })

  // Use the composable's addNewRow function which properly handles ag-Grid
  addNewRow(selectedStaffId.value, currentDate.value, staffData)

  hasUnsavedChanges.value = true

  debugLog('Added new entry via composable')
}

const reloadData = () => {
  error.value = null
  loadTimesheetData()
}

const refreshData = () => {
  reloadData()
}

const handleStaffChange = async (staffId: string | null) => {
  if (!staffId) {
    debugLog('Skipping staff change - no staffId provided')
    return
  }

  if (staffId === selectedStaffId.value) {
    debugLog('Skipping staff change - same staff selected')
    return
  }

  debugLog('Staff changed:', { from: selectedStaffId.value, to: staffId })

  selectedStaffId.value = staffId
  updateRoute()

  // ✅ Use debounced version and don't await to prevent blocking UI
  debouncedLoadTimesheetData()
}

const loadTimesheetData = async () => {
  debugLog('function loadTimesheetData called with:', {
    staffId: selectedStaffId.value,
    date: currentDate.value,
    isInitializing: isInitializing.value,
    isLoadingData: isLoadingData.value,
  })

  debugLog('Call-stack: ', new Error().stack)
  debugLog('Timestamp:', new Date().toISOString())

  // ✅ Prevent duplicate calls
  if (isLoadingData.value) {
    debugLog('Skipping data load - already loading')
    return
  }

  if (!selectedStaffId.value) {
    debugLog('Skipping data load - no staff selected')
    return
  }

  if (!currentDate.value) {
    debugLog('Skipping data load - no date selected')
    return
  }

  try {
    loading.value = true
    isLoadingData.value = true // ✅ Set loading flag
    error.value = null

    debugLog('Loading timesheet data for:', {
      staffId: selectedStaffId.value,
      date: currentDate.value,
    })

    const response = await costlineService.getTimesheetEntries(
      selectedStaffId.value,
      currentDate.value,
    )

    debugLog('API Response:', response)
    debugLog('Cost lines from API:', response.cost_lines)
    debugLog('Number of cost lines:', response.cost_lines?.length || 0)

    timeEntries.value = response.cost_lines.map((line: TimesheetCostLine) => {
      const hours = line.quantity
      const staffWageRate = line.wage_rate || line.unit_cost
      const metaRecord = toMetaRecord(line.meta) as RateMultiplierMetaRecord | null
      const rateMultiplier = metaRecord?.wage_rate_multiplier as number

      // Always calculate wage with correct formula: hours * rate_multiplier * staff_wage_rate
      const calculatedWage =
        hours > 0 && staffWageRate > 0
          ? Math.round(hours * rateMultiplier * staffWageRate * 100) / 100
          : 0

      debugLog('[Timesheet] Loading entry with correct wage calculation:', {
        id: line.id,
        hours,
        staffWageRate,
        rateMultiplier,
        calculatedWage,
        backendWage: line.total_cost,
        formula: `${hours} * ${rateMultiplier} * ${staffWageRate} = ${calculatedWage}`,
      })

      const normalizedJobId = line.job_id || ''
      const normalizedJobNumber =
        typeof line.job_number === 'number' ? line.job_number : Number(line.job_number) || 0
      const normalizedJobNumberString = line.job_number != null ? String(line.job_number) : ''
      const normalizedClientName = line.client_name || ''
      const normalizedJobName = line.job_name || ''
      const normalizedChargeOutRate = line.charge_out_rate || 0

      return {
        ...line,
        jobId: normalizedJobId,
        job_id: normalizedJobId,
        jobNumber: normalizedJobNumberString,
        job_number: normalizedJobNumber,
        client: normalizedClientName,
        client_name: normalizedClientName,
        jobName: normalizedJobName,
        job_name: normalizedJobName,
        hours,
        billable:
          typeof metaRecord?.['is_billable'] === 'boolean'
            ? (metaRecord['is_billable'] as boolean)
            : true,
        description: line.desc,
        rate: getRateTypeFromMultiplier(rateMultiplier),
        wage: calculatedWage,
        bill: line.total_rev,
        staffId: selectedStaffId.value,
        date: currentDate.value,
        wageRate: staffWageRate,
        chargeOutRate: normalizedChargeOutRate,
        charge_out_rate: normalizedChargeOutRate,
        rateMultiplier,
        xeroPayItemId: line.xero_pay_item,
        xeroPayItemName: line.xero_pay_item_name,
        isNewRow: false,
        isModified: false,
      } as TimesheetEntryViewRow
    })

    // Sort by creation time so entries stay in the order they were entered
    timeEntries.value.sort((a, b) => {
      const aTime = a.created_at ?? ''
      const bTime = b.created_at ?? ''
      return aTime < bTime ? -1 : aTime > bTime ? 1 : 0
    })

    scheduledHours.value = response.summary.scheduled_hours as number

    const staffData = timesheetStore.staff.find((s) => s.id === selectedStaffId.value)
    loadData(timeEntries.value, selectedStaffId.value, staffData)

    debugLog(`Loaded ${timeEntries.value.length} timesheet entries`)
  } catch (err) {
    debugLog('Error loading timesheet data:', err)
    error.value = 'Failed to load timesheet data'
  } finally {
    loading.value = false
    isLoadingData.value = false // ✅ Clear loading flag
  }
}

// ✅ Create debounced version to prevent rapid successive calls
const debouncedLoadTimesheetData = debounce(loadTimesheetData, 1000)

const getRateTypeFromMultiplier = (multiplier: number): string => {
  switch (multiplier) {
    case 1.0:
      return 'Ord'
    case 1.5:
      return '1.5'
    case 2.0:
      return '2.0'
    case 0.0:
      return 'Unpaid'
    default:
      return 'Ord'
  }
}

const handleKeydown = (event: KeyboardEvent) => {
  const target = event.target as HTMLElement
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
    return
  }

  const staffData = timesheetStore.staff.find((s) => s.id === selectedStaffId.value)
  if (handleKeyboardShortcut(event, selectedStaffId.value, staffData)) {
    return
  }

  if (event.ctrlKey || event.metaKey) {
    switch (event.key) {
      case 'n':
        event.preventDefault()
        addNewEntry()
        break
      case 's':
        event.preventDefault()
        if (autosave.isIdle()) {
          toast.success('All changes saved')
        } else {
          toast.info('Saving entries...')
        }
        break
    }
  }

  if (event.shiftKey && event.key === 'N') {
    event.preventDefault()
    event.stopPropagation()
    debugLog('Shift+N pressed - adding new entry')
    addNewEntry()
  }
}

onMounted(async () => {
  try {
    loading.value = true

    debugLog('Initializing optimized timesheet...')

    // initialize() already calls loadStaff, loadJobs, loadCompanyDefaults in parallel
    // No need to call them again - that was causing duplicate API calls
    await Promise.all([timesheetStore.initialize(), companyDefaultsStore.loadCompanyDefaults()])
    debugLog('Company Defaults store value: ', companyDefaultsStore.companyDefaults)

    let validStaffId = selectedStaffId.value

    if (validStaffId && !timesheetStore.staff.find((s: Staff) => s.id === validStaffId)) {
      error.value =
        `Staff ${validStaffId} is not available for timesheet entry. ` +
        `They are not in the active timesheet staff list (typically because they have ` +
        `no Xero payroll ID configured).`
      loading.value = false
      isInitializing.value = false
      return
    }

    if (!validStaffId && timesheetStore.staff.length > 0) {
      validStaffId = timesheetStore.staff[0].id
      debugLog('No staffId in URL, using first available:', validStaffId)
    }

    selectedStaffId.value = validStaffId

    const currentStaffData = timesheetStore.staff.find((s: Staff) => s.id === validStaffId)

    debugLog('Available staff:', timesheetStore.staff.length)
    debugLog('Available jobs:', timesheetStore.jobs.length)
    debugLog(
      'Current staff for calculations:',
      currentStaffData?.name,
      'wage rate:',
      currentStaffData?.wageRate,
    )
    debugLog('Company defaults for calculations:', companyDefaultsStore.companyDefaults)

    updateRoute()

    isInitializing.value = false

    debugLog('Starting initial data load...')
    await loadTimesheetData()

    // Load enhanced job data for jobs with timesheet entries
    const costLineEntries = adaptedTimeEntries.value as TimesheetEntryViewRow[]
    const jobsWithEntries = activeJobs.value.filter(
      (job) => getJobHours(job.id, costLineEntries) > 0,
    )
    if (jobsWithEntries.length > 0) {
      await loadEnhancedJobData(jobsWithEntries.map((job) => job.id))
    }

    window.addEventListener('keydown', handleKeydown)

    debugLog('Optimized timesheet initialized successfully')
  } catch (err) {
    debugLog('Error initializing optimized timesheet:', err)
    error.value = 'Failed to initialize timesheet'
  }
})

watch(
  [selectedStaffId, currentDate],
  async ([newStaffId, newDate], [oldStaffId, oldDate]) => {
    if (!newStaffId || !newDate) {
      debugLog('Skipping watcher - missing staffId or date')
      return
    }

    if (newStaffId === oldStaffId && newDate === oldDate) {
      debugLog('Skipping watcher - no actual change')
      return
    }

    if (isInitializing.value) {
      debugLog('Skipping watcher - still initializing')
      return
    }

    if (!oldStaffId || !oldDate) {
      debugLog('Skipping watcher - initial setup detected')
      return
    }

    selectedStaffId.value = newStaffId
    updateRoute()

    const staffData = timesheetStore.staff.find((s) => s.id === selectedStaffId.value) || null
    setCurrentStaff(staffData)

    debugLog('Loading data due to staff/date change:', {
      newStaffId,
      newDate,
      oldStaffId,
      oldDate,
    })
    // ✅ Use debounced version to prevent rapid calls
    debouncedLoadTimesheetData()
  },
  { immediate: false },
)

watch(
  () => route.query,
  (newQuery, oldQuery) => {
    if (isInitializing.value) {
      debugLog('Skipping URL watcher - still initializing')
      return
    }

    debugLog('URL query changed:', { old: oldQuery, new: newQuery })

    let hasChanges = false

    if (newQuery.date && newQuery.date !== currentDate.value) {
      debugLog('Updating date from URL:', newQuery.date)
      currentDate.value = newQuery.date as string
      hasChanges = true
    }

    if (newQuery.staffId && newQuery.staffId !== selectedStaffId.value) {
      const staffExists = timesheetStore.staff.find((s: Staff) => s.id === newQuery.staffId)
      if (staffExists) {
        debugLog('Updating staff from URL:', newQuery.staffId)
        selectedStaffId.value = newQuery.staffId as string
        hasChanges = true
      } else {
        debugLog('Staff ID from URL not found:', newQuery.staffId)
      }
    }

    if (hasChanges) {
      debugLog('Reloading data due to URL changes')
      // ✅ Use debounced version to prevent rapid calls
      debouncedLoadTimesheetData()
    }
  },
  { immediate: false },
)

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
:deep(.ag-theme-custom) {
  --ag-header-height: 40px;
  --ag-row-height: 35px;
  --ag-header-background-color: #181f2a;
  --ag-header-foreground-color: #f3f4f6;
  --ag-odd-row-background-color: rgb(248, 250, 252);
  --ag-row-hover-color: rgb(241, 245, 249);
  --ag-selected-row-background-color: rgb(219, 234, 254);
  --ag-border-color: rgb(226, 232, 240);
  --ag-font-size: 13px;
}

@media (max-width: 1024px) {
  :deep(.ag-theme-custom) {
    --ag-header-height: 36px;
    --ag-row-height: 32px;
    --ag-font-size: 12px;
  }

  :deep(.ag-theme-custom .ag-header-cell) {
    padding: 0 4px;
  }

  :deep(.ag-theme-custom .ag-cell) {
    padding: 0 4px;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='client_name']),
  :deep(.ag-theme-custom .ag-cell[col-id='client_name']) {
    display: none;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='rate']),
  :deep(.ag-theme-custom .ag-cell[col-id='rate']) {
    display: none;
  }
}

@media (max-width: 640px) {
  :deep(.ag-theme-custom) {
    --ag-header-height: 32px;
    --ag-row-height: 28px;
    --ag-font-size: 11px;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='job_name']),
  :deep(.ag-theme-custom .ag-cell[col-id='job_name']) {
    display: none;
  }

  :deep(.ag-theme-custom .ag-header-cell[col-id='wage']),
  :deep(.ag-theme-custom .ag-cell[col-id='wage']) {
    display: none;
  }
}

:deep(.ag-theme-custom .ag-header-cell) {
  font-weight: 700;
  background: var(--ag-header-background-color) !important;
  color: var(--ag-header-foreground-color) !important;
  border-bottom: 1.5px solid #334155;
}

:deep(.ag-theme-custom .ag-cell) {
  border-right: 1px solid var(--ag-border-color);
}

:deep(.ag-theme-custom .ag-row-selected) {
  border: 1px solid rgb(59, 130, 246);
}

:deep(.ag-theme-custom .ag-body-horizontal-scroll) {
  height: 14px !important;
}

:deep(.ag-theme-custom .ag-body-vertical-scroll) {
  width: 14px !important;
}

kbd {
  font-family:
    ui-monospace, SFMono-Regular, 'SF Mono', Consolas, 'Liberation Mono', Menlo, monospace;
}
</style>
