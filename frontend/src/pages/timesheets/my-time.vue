<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCompanyDefaultsStore } from '@/stores/companyDefaults'
import { computed, onMounted, ref, watch } from 'vue'
import '@kodeglot/vue-calendar/style.css'
import WorkshopMyTimeHeader from '@/components/workshop/WorkshopMyTimeHeader.vue'
import WorkshopTimesheetSummaryCard from '@/components/workshop/WorkshopTimesheetSummaryCard.vue'
import WorkshopTimesheetLegacyTable from '@/components/workshop/WorkshopTimesheetLegacyTable.vue'
import WorkshopTimesheetCalendar from '@/components/workshop/WorkshopTimesheetCalendar.vue'
import WorkshopTimesheetEntryDrawer from '@/components/workshop/WorkshopTimesheetEntryDrawer.vue'
import WorkshopJobPickerDrawer from '@/components/workshop/WorkshopJobPickerDrawer.vue'
import {
  formatDateKey,
  formatFullDate,
  parseDateKey,
  useWorkshopTimesheetDay,
} from '@/composables/useWorkshopTimesheetDay'
import { useWorkshopTimesheetJobs } from '@/composables/useWorkshopTimesheetJobs'
import { useWorkshopTimesheetForm } from '@/composables/useWorkshopTimesheetForm'
import { useWorkshopCalendarSync } from '@/composables/useWorkshopCalendarSync'
import { useWorkshopJobBudgets } from '@/composables/useWorkshopJobBudgets'

const selectedDate = ref(formatDateKey(new Date()))
const isDayLoading = ref(false)
const isJobPickerOpen = ref(false)

const {
  dailyData,
  selectedEntries,
  selectedDaySummary,
  requiresLegacyFallback,
  selectedJobIds,
  loadDay,
} = useWorkshopTimesheetDay(selectedDate)
const { jobs, jobSearch, filteredJobs, loadJobs } = useWorkshopTimesheetJobs()
const { overBudgetJobs, overBudgetTooltip, refreshJobBudgets, getJobBudgetState } =
  useWorkshopJobBudgets(selectedJobIds)

const {
  formState,
  editingEntryId,
  isFormOpen,
  isSubmitting,
  formDurationHours,
  openCreateForm,
  openEditForm,
  submitForm,
  handleDeleteEntry,
  deleteEntryFromDrawer,
  resetForm,
  setRangeToNow,
  adjustRangeBy,
  fillGapToNextEntry,
  resetToDefaultRange,
  displayRate,
  safeRateMultiplier,
} = useWorkshopTimesheetForm({
  selectedDate,
  selectedEntries,
  loadDay,
  isDayLoading,
})

const selectedJob = computed(() => jobs.value.find((job) => job.id === formState.jobId) ?? null)
const selectedJobLabel = computed(() =>
  selectedJob.value ? `#${selectedJob.value.job_number} - ${selectedJob.value.name}` : null,
)
const selectedDateLabel = computed(() => formatFullDate(parseDateKey(selectedDate.value)))

function selectDay(dateKey: string) {
  selectedDate.value = dateKey
}

function shiftDay(delta: number) {
  const currentSelected = parseDateKey(selectedDate.value)
  currentSelected.setDate(currentSelected.getDate() + delta)
  selectedDate.value = formatDateKey(currentSelected)
}

function handleJobSelect(jobId: string) {
  formState.jobId = jobId
  isJobPickerOpen.value = false
}

const {
  calendarStore,
  calendarViewRef,
  handleCalendarOpenEventModal,
  handleCalendarEventClick,
  handleCalendarDateChange,
  scheduleModalSuppression,
} = useWorkshopCalendarSync({
  selectedDate,
  selectedEntries,
  requiresLegacyFallback,
  getJobBudgetState,
  onCreateEntry: openCreateForm,
  onEditEntry: openEditForm,
  onSelectDay: selectDay,
})

const setCalendarViewRef = (instance: typeof calendarViewRef.value) => {
  calendarViewRef.value = instance
}

const companyDefaultsStore = useCompanyDefaultsStore()

watch(
  selectedJobIds,
  (jobIds) => {
    void refreshJobBudgets(jobIds)
  },
  { immediate: true },
)

watch(
  selectedDate,
  (dateKey) => {
    if (!dailyData.value[dateKey]) {
      void loadDay(dateKey)
    }
    calendarStore.currentDate = parseDateKey(dateKey)
  },
  { immediate: true },
)

onMounted(() => {
  calendarStore.currentDate = parseDateKey(selectedDate.value)
  void loadJobs()
  if (!companyDefaultsStore.isLoaded && !companyDefaultsStore.isLoading) {
    void companyDefaultsStore.loadCompanyDefaults()
  }
  scheduleModalSuppression()
})
</script>

<template>
  <AppLayout>
    <div class="flex flex-col min-h-full bg-muted/10">
      <WorkshopMyTimeHeader :formatted-date="selectedDateLabel" @shift="shiftDay" />

      <main class="flex-1 max-h-none min-h-full px-4 py-4 sm:px-6 space-y-4">
        <WorkshopTimesheetSummaryCard
          :formatted-date="selectedDateLabel"
          :over-budget-jobs-count="overBudgetJobs.length"
          :over-budget-tooltip="overBudgetTooltip"
          :selected-day-summary="selectedDaySummary"
          :is-day-loading="isDayLoading"
          @refresh="loadDay(selectedDate)"
          @add="openCreateForm"
        >
          <div class="space-y-4">
            <div
              v-if="isDayLoading && selectedEntries.length === 0"
              class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
            >
              <Card v-for="i in 3" :key="i" class="shadow-sm border">
                <CardContent class="p-4 space-y-3">
                  <Skeleton class="h-4 w-24" />
                  <Skeleton class="h-4 w-32" />
                  <Skeleton class="h-4 w-20" />
                  <Skeleton class="h-10 w-full" />
                </CardContent>
              </Card>
            </div>

            <div v-else>
              <WorkshopTimesheetLegacyTable
                v-if="requiresLegacyFallback"
                :entries="selectedEntries"
                :display-rate="displayRate"
                :safe-rate-multiplier="safeRateMultiplier"
                @edit="openEditForm"
                @delete="handleDeleteEntry"
              />

              <div v-else class="space-y-3">
                <p
                  v-if="selectedEntries.length === 0 && !isDayLoading"
                  class="text-center text-sm text-muted-foreground"
                >
                  No entries yet. Tap the calendar to add the first block.
                </p>
                <WorkshopTimesheetCalendar
                  :initial-date="parseDateKey(selectedDate)"
                  :on-calendar-ready="setCalendarViewRef"
                  :on-open-event-modal="handleCalendarOpenEventModal"
                  :on-event-click="handleCalendarEventClick"
                  :on-date-change="handleCalendarDateChange"
                />
              </div>
            </div>
          </div>
        </WorkshopTimesheetSummaryCard>
      </main>
    </div>
  </AppLayout>

  <WorkshopTimesheetEntryDrawer
    v-model:open="isFormOpen"
    :editing-entry-id="editingEntryId"
    :form-state="formState"
    :form-duration-hours="formDurationHours"
    :selected-date-label="selectedDateLabel"
    :selected-job-label="selectedJobLabel"
    :is-submitting="isSubmitting"
    :is-day-loading="isDayLoading"
    :on-open-job-picker="() => (isJobPickerOpen = true)"
    :on-delete-entry="deleteEntryFromDrawer"
    :on-submit="submitForm"
    :on-reset-form="resetForm"
    :on-set-range-now="setRangeToNow"
    :on-adjust-range-by="adjustRangeBy"
    :on-fill-gap="fillGapToNextEntry"
    :on-reset-range="resetToDefaultRange"
    @update:formState="(value) => Object.assign(formState, value)"
  />

  <WorkshopJobPickerDrawer
    v-model:open="isJobPickerOpen"
    :job-search="jobSearch"
    :filtered-jobs="filteredJobs"
    @update:jobSearch="(value) => (jobSearch = value)"
    @select="handleJobSelect"
  />
</template>
